"""Predicted KV-memory limit (concurrent resident sessions) for a model on one GPU under vLLM.

    python harness/kv_limit.py                      # Qwen3-8B, A100-40GB, util 0.9, ctx 4k/8k/20k
    python harness/kv_limit.py --ctx 4096 8192 --util 0.9

Pure arithmetic on the HF config + safetensors index; safe to run on a login node.

Model of vLLM's budget (V1 engine):  KV = util * total - weights - overhead
  overhead = peak activations during the profiling run + non-torch memory (cuBLAS/NCCL) + CUDA graphs.
  It isn't in any config, so it is a range here; vLLM prints the real "Available KV cache memory"
  and "GPU KV cache size: N tokens" at startup, which G3's first job records to check this.
"""
import argparse, glob, json, os

GiB = 2**30
# torch.cuda.get_device_properties(0).total_memory on a Perlmutter A100-SXM4-40GB, measured in job 60824576.
# (Prediction 1a was computed with an assumed 42,298,834,944 B; the 0.25% difference is ~+700 KV tokens.)
A100_40GB_BYTES = 42_404_806_656
DTYPE_BYTES = {"bfloat16": 2, "float16": 2, "float32": 4}


def snapshot(model):
    hub = os.path.join(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")), "hub")
    snaps = glob.glob(os.path.join(hub, "models--" + model.replace("/", "--"), "snapshots", "*"))
    if not snaps:
        raise SystemExit(f"{model} not in {hub}")
    return snaps[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("DBKV_MODEL", "Qwen/Qwen3-8B"))
    ap.add_argument("--gpu-bytes", type=int, default=A100_40GB_BYTES)
    ap.add_argument("--util", type=float, default=0.9)
    ap.add_argument("--ctx", type=int, nargs="+", default=[4096, 8192, 20480])
    ap.add_argument("--overhead-gib", type=float, nargs=3, default=[1.0, 2.0, 3.0],
                    metavar=("LOW", "MID", "HIGH"), help="activations + non-torch + CUDA graphs")
    ap.add_argument("--block", type=int, default=16, help="vLLM KV block size (tokens)")
    a = ap.parse_args()

    snap = snapshot(a.model)
    cfg = json.load(open(os.path.join(snap, "config.json")))
    weights = json.load(open(os.path.join(snap, "model.safetensors.index.json")))["metadata"]["total_size"]
    L, kvh = cfg["num_hidden_layers"], cfg["num_key_value_heads"]
    hd = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
    dt = DTYPE_BYTES[cfg.get("torch_dtype", "bfloat16")]
    per_tok = 2 * L * kvh * hd * dt  # K and V, every layer

    budget = a.util * a.gpu_bytes
    print(f"{a.model}: {L} layers x {kvh} KV heads x head_dim {hd} x {dt} B x 2 (K,V) "
          f"= {per_tok} B/token ({per_tok / 1024:.0f} KiB)")
    print(f"GPU {a.gpu_bytes / GiB:.2f} GiB x util {a.util} = {budget / GiB:.2f} GiB; "
          f"weights {weights / GiB:.2f} GiB; overhead {a.overhead_gib} GiB (low/mid/high)\n")
    print(f"{'overhead':>9} {'KV GiB':>7} {'KV tokens':>10}  " +
          "  ".join(f"{'ctx ' + str(c):>10}" for c in a.ctx))
    for ov, label in zip(sorted(a.overhead_gib, reverse=True), ("high", "mid", "low")):
        kv = budget - weights - ov * GiB
        toks = int(kv // per_tok) // a.block * a.block
        per_sess = [-(-c // a.block) * a.block for c in a.ctx]  # round up to whole blocks
        print(f"{label:>9} {kv / GiB:7.2f} {toks:10,d}  " +
              "  ".join(f"{toks / s:10.1f}" for s in per_sess))
    print("\nColumns under ctx = sessions whose full context fits in the KV pool at once (the memory limit).")


if __name__ == "__main__":
    main()
