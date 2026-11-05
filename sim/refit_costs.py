"""Fit the simulator's GPU cost parameters (Cfg.t0, c_pf, c_dec, c_att, kv_tokens) to G3 measurements.

  python sim/refit_costs.py $SCRATCH/dbkv/runs/g3/main --out results/g3_costs.json

Model (same as sim/kvsim.py): one engine iteration takes
    dt = t0 + c_pf * prefill_tokens + c_dec * R + c_att * R * ctx
with R running sequences of ~ctx resident tokens each.
  * c_pf: from turn-0 TTFT at the lightest-load point per context (a fresh prefill of C0 tokens),
    as (ttft_p50 - t_one_iter) / C0.
  * Decode: per point, tau = mean (e2e - ttft) / (out - 1) seconds per output token; the uncached prefill
    rate P (tokens/s) comes from vLLM's counters, so per iteration ~P*tau prefill tokens are mixed in:
        tau * (1 - c_pf * P) = t0 + c_dec * R + c_att * R * ctx      (least squares over points)
    R = mean vllm:num_requests_running over the measured window.
  * kv_tokens: vLLM's reported "GPU KV cache size" (kv_actual.txt).
Points come from rep*/c*_n*_r0/{summary.json, turns.csv, metrics.jsonl}.
"""
import argparse, csv, glob, json, os, re

import numpy as np


def load(run):
    pts = []
    for sp in glob.glob(os.path.join(run, "rep*", "c*_n*_r0", "summary.json")):
        d = json.load(open(sp)); dd = os.path.dirname(sp)
        w = d["warmup"]
        turns = [x for x in csv.DictReader(open(os.path.join(dd, "turns.csv"))) if float(x["t_req"]) >= w]
        dec = [(float(x["e2e"]) - float(x["ttft"])) / max(1, int(x["out"]) - 1) for x in turns if int(x["out"]) > 1]
        t0s = [float(x["ttft"]) for x in turns if x["turn"] == "0"]
        c0s = [int(x["ctx"]) for x in turns if x["turn"] == "0"]
        R = [json.loads(l).get("vllm:num_requests_running") for l in open(os.path.join(dd, "metrics.jsonl"))]
        R = [r for r, l in zip(R, open(os.path.join(dd, "metrics.jsonl"))) if r is not None and json.loads(l)["t"] >= w]
        P = (d["prompt_tokens"] - d["prompt_tokens_cached"]) / d["duration"] if d.get("duration") else 0.0
        pts.append(dict(ctx=d["ctx"], n=d["sessions"], tau=float(np.median(dec)) if dec else np.nan,
                        R=float(np.mean(R)) if R else np.nan, P=P,
                        ttft0=float(np.median(t0s)) if t0s else np.nan, c0=int(np.median(c0s)) if c0s else 0,
                        task_p95=d["task_p95"], resume_p95=d["resume_ttft_p95"], rep=sp.split(os.sep)[-3]))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    pts = [p for p in load(a.run) if p["tau"] == p["tau"] and p["R"] == p["R"]]
    kv = None
    for f in glob.glob(os.path.join(a.run, "kv_actual*.txt")) + [os.path.join(a.run, "kv_actual.txt")]:
        if os.path.exists(f):
            m = re.findall(r"GPU KV cache size: ([\d,]+) tokens", open(f).read())
            if m:
                kv = int(m[-1].replace(",", ""))
    # prefill rate from the lightest point per context
    cpf = []
    for ctx in sorted({p["ctx"] for p in pts}):
        lo = min((p for p in pts if p["ctx"] == ctx), key=lambda p: p["n"])
        if lo["ttft0"] == lo["ttft0"] and lo["c0"]:
            cpf.append(lo["ttft0"] / lo["c0"])
    c_pf = float(np.median(cpf))
    # decode fit only where prefill takes < half the GPU time; above the limit the GPU saturates on
    # recompute (P ~ 1/c_pf) and tau*(1 - c_pf*P) is ill-conditioned
    fit = [p for p in pts if c_pf * p["P"] < 0.5]
    A = np.array([[1.0, p["R"], p["R"] * p["ctx"]] for p in fit])
    y = np.array([p["tau"] * (1 - c_pf * p["P"]) for p in fit])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    t0, c_dec, c_att = (max(0.0, float(c)) for c in coef)  # non-negative; no floor
    pred = A @ np.array([t0, c_dec, c_att])
    r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
    out = dict(t0=round(t0, 6), c_pf=float(f"{c_pf:.3e}"), c_dec=float(f"{c_dec:.3e}"), c_att=float(f"{c_att:.3e}"))
    if kv:
        out["kv_tokens"] = kv
    meta = dict(points=len(pts), decode_fit_points=len(fit), r2_decode=round(float(r2), 3), prefill_tok_s=round(1 / c_pf),
                guessed=dict(t0=0.012, c_pf=1e-4, c_dec=2e-4, c_att=1e-7, kv_tokens=134448))
    print(json.dumps(out), json.dumps(meta))
    for p in sorted(pts, key=lambda p: (p["ctx"], p["n"])):
        print(f"  ctx {p['ctx']:5d} n {p['n']:3d} {p['rep']}: tau {1000 * p['tau']:6.1f} ms/token  R {p['R']:5.1f}  "
              f"P {p['P']:7.0f} tok/s  ttft0 {p['ttft0']:.2f} s")
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1)
        json.dump(meta, open(a.out.replace(".json", "_meta.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
