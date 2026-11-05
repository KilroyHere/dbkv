"""Test 1 (D5) analysis, exactly as pre-registered in PLAN §2b.

  python harness/d5_analyze.py $DBKV_DATA/runs/d5/<job> --out results/d5_summary.md
"""
import argparse, csv, glob, json, os

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    idle = list(csv.DictReader(open(os.path.join(a.run, "idle", "idle.csv"))))
    f = lambda r, k: float(r[k]) if r[k] not in ("", "None") else np.nan  # noqa: E731
    client_min = float(np.nanmedian([f(r, "rest_ms") for r in idle if r["kind"] == "one_token"]))
    tok = {int(r["ctx"]): float(r["ms"]) for r in csv.DictReader(open(os.path.join(a.run, "idle", "tokenize.csv")))}
    tx, ty = zip(*sorted(tok.items()))
    tokenize = lambda n: float(np.interp(n, tx, ty, left=ty[0] * n / tx[0]))  # noqa: E731

    lines = ["# Test 1 (D5): resume-overhead breakdown", "",
             f"Run `{a.run}`. Rule (PLAN §2b): mean over the 4 loaded points of p95(engine_overhead) / p95(turn e2e) "
             ">= 10% means pursue stateful sessions; < 10% means drop.", "",
             f"client_min (median `rest` of a 1-token request on an idle server) = {client_min:.2f} ms. "
             f"Tokenizer time for re-sending the prompt as text: " +
             ", ".join(f"{k // 1024}k {v:.1f} ms" for k, v in sorted(tok.items())) + ".", "",
             "## Idle single requests (medians, ms)", "",
             "| kind | ctx | client TTFT | queue | engine TTFT (prefill) | rest |", "|---|---|---|---|---|---|"]
    for kind in ("one_token", "fresh", "resume"):
        for ctx in sorted({int(r["ctx"]) for r in idle if r["kind"] == kind}):
            rs = [r for r in idle if r["kind"] == kind and int(r["ctx"]) == ctx]
            md = lambda k: np.nanmedian([f(r, k) for r in rs])  # noqa: E731
            lines.append(f"| {kind} | {ctx} | {md('client_ttft_ms'):.1f} | {md('queue_ms'):.2f} | "
                         f"{md('engine_ttft_ms'):.1f} | {md('rest_ms'):.1f} |")
    lines += ["", "## Loaded points: resumed turns (turn > 0, after warm-up)", "",
              "| point | resumes | TTFT p50 / p95 | queue p50 / p95 | prefill p50 / p95 | rest p50 / p95 | "
              "engine_overhead p50 / p95 | turn e2e p95 | ratio |", "|---|---|---|---|---|---|---|---|---|"]
    ratios = []
    for d in sorted(glob.glob(os.path.join(a.run, "loaded", "c*_n*_r0"))):
        s = json.load(open(os.path.join(d, "summary.json")))
        t = [r for r in csv.DictReader(open(os.path.join(d, "turns.csv")))
             if r["turn"] != "0" and float(r["t_req"]) >= s["warmup"] and r["queue_ms"] not in ("", "None")]
        ttft = np.array([1000 * float(r["ttft"]) for r in t]); q = np.array([float(r["queue_ms"]) for r in t])
        pf = np.array([float(r["engine_ttft_ms"]) for r in t]); e2e = np.array([1000 * float(r["e2e"]) for r in t])
        rest = ttft - q - pf
        eo = rest - client_min + np.array([tokenize(int(r["prompt"])) for r in t])
        ratio = float(np.percentile(eo, 95) / np.percentile(e2e, 95))
        ratios.append(ratio)
        p = lambda x: f"{np.percentile(x, 50):.0f} / {np.percentile(x, 95):.0f}"  # noqa: E731
        lines.append(f"| {s['ctx'] // 1024}k × {s['sessions']} | {len(t)} | {p(ttft)} | {p(q)} | {p(pf)} | {p(rest)} | "
                     f"{p(eo)} | {np.percentile(e2e, 95):.0f} | {100 * ratio:.1f}% |")
    mean = float(np.mean(ratios))
    verdict = "PURSUE stateful sessions" if mean >= 0.10 else "DROP stateful sessions"
    lines += ["", f"**Mean ratio over {len(ratios)} points: {100 * mean:.1f}% → {verdict}** (rule: ≥ 10% pursue).", ""]
    open(a.out, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    json.dump(dict(mean_ratio=mean, ratios=ratios, client_min_ms=client_min, verdict=verdict),
              open(a.out.replace(".md", ".json"), "w"), indent=1)


if __name__ == "__main__":
    main()
