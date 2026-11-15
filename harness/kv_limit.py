"""Predicted KV-memory limit (concurrent resident sessions) for a model under vLLM, on 1 GPU or with TP.

    python harness/kv_limit.py --model Qwen/Qwen3-8B             # the 8B record: 1 A100-40GB, util 0.9, ctx 4k/8k/20k
    python harness/kv_limit.py --model Qwen/Qwen3-32B --tp 4 --task-kv 2200 2900
                                                                  # PLAN 2j: TP=4 on a full node, and the admission limit K

With --tp N the weights and the KV heads are split over N GPUs (vLLM shards attention by KV head; if N > KV heads,
heads are replicated). Every GPU holds the same token count, so the pool in tokens = per-GPU KV bytes / per-GPU
bytes per token. --task-kv gives the KV per active task in tokens (measured: pool x peak KV usage / active tasks,
the rule that gave K = 77 / 72 for 8B), and the script prints K = floor(pool / task KV) for each.

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
    ap.add_argument("--tp", type=int, default=1, help="tensor-parallel size (GPUs per vLLM instance)")
    ap.add_argument("--task-kv", type=int, nargs="*", default=[],
                    help="KV tokens per active task; prints the admission limit K = floor(pool / task KV)")
    ap.add_argument("--gpu-bytes", type=int, default=A100_40GB_BYTES)
    ap.add_argument("--util", type=float, default=0.9)
    ap.add_argument("--ctx", type=int, nargs="+", default=[4096, 8192, 20480])
    ap.add_argument("--overhead-gib", type=float, nargs=3, default=None, metavar=("LOW", "MID", "HIGH"),
                    help="per GPU: activations + non-torch + CUDA graphs (+ NCCL / custom all-reduce buffers "
                         "with TP). Default 1/2/3 GiB at TP 1, 1.5/2.5/3.5 GiB at TP > 1")
    ap.add_argument("--block", type=int, default=16, help="vLLM KV block size (tokens)")
    a = ap.parse_args()
    if a.overhead_gib is None:
        a.overhead_gib = [1.0, 2.0, 3.0] if a.tp == 1 else [1.5, 2.5, 3.5]

    snap = snapshot(a.model)
    cfg = json.load(open(os.path.join(snap, "config.json")))
    weights = json.load(open(os.path.join(snap, "model.safetensors.index.json")))["metadata"]["total_size"]
    L, kvh = cfg["num_hidden_layers"], cfg["num_key_value_heads"]
    hd = cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"]
    dt = DTYPE_BYTES[cfg.get("torch_dtype", "bfloat16")]
    per_tok = 2 * L * kvh * hd * dt  # K and V, every layer (whole model)
    kvh_gpu = max(1, kvh // a.tp)  # KV heads held by each GPU (replicated if tp > kvh)
    per_tok_gpu = 2 * L * kvh_gpu * hd * dt
    w_gpu = weights / a.tp  # ignores small replicated tensors (norms)

    budget = a.util * a.gpu_bytes
    print(f"{a.model}: {L} layers x {kvh} KV heads x head_dim {hd} x {dt} B x 2 (K,V) "
          f"= {per_tok} B/token ({per_tok / 1024:.0f} KiB)")
    if a.tp > 1:
        print(f"TP {a.tp}: {kvh_gpu} KV heads per GPU -> {per_tok_gpu / 1024:.0f} KiB/token per GPU; "
              f"weights {weights / GiB:.2f} GiB total, {w_gpu / GiB:.2f} GiB per GPU")
    print(f"per GPU: {a.gpu_bytes / GiB:.2f} GiB x util {a.util} = {budget / GiB:.2f} GiB; "
          f"weights {w_gpu / GiB:.2f} GiB; overhead {a.overhead_gib} GiB (low/mid/high)\n")
    hdr = "  ".join(f"{'ctx ' + str(c):>10}" for c in a.ctx)
    hdr_k = "  ".join(f"{'K@' + str(t):>8}" for t in a.task_kv)
    print(f"{'overhead':>9} {'KV GiB/GPU':>10} {'KV tokens':>10}  {hdr}  {hdr_k}")
    for ov, label in zip(sorted(a.overhead_gib, reverse=True), ("high", "mid", "low")):
        kv = budget - w_gpu - ov * GiB
        toks = int(kv // per_tok_gpu) // a.block * a.block
        per_sess = [-(-c // a.block) * a.block for c in a.ctx]  # round up to whole blocks
        ks = "  ".join(f"{toks // t:8d}" for t in a.task_kv)
        print(f"{label:>9} {kv / GiB:10.2f} {toks:10,d}  " +
              "  ".join(f"{toks / s:10.1f}" for s in per_sess) + f"  {ks}")
    print("\nColumns under ctx = sessions whose full context fits in the KV pool at once (the memory limit).")
    if a.task_kv:
        print("K@t = admission limit floor(pool / t) for t KV tokens per active task. Use vLLM's reported pool "
              "('GPU KV cache size: N tokens') once a server has started.")


if __name__ == "__main__":
    main()
