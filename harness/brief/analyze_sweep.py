"""D2 step 6 analysis (PLAN §2d): concurrency sweep, prefix caching on/off.

  python harness/brief/analyze_sweep.py --on RUN_ON --off RUN_OFF --out results/d2_step6.md
Cells are <RUN>/<arm>_c<conc>/{tasks,turns}.jsonl + metrics.jsonl (2 s samples of /metrics).
"""
import argparse, json, os

import numpy as np

ARMS = ["explore", "full", "lexical", "oracle"]
CONCS = [8, 32, 64]


def cell(d):
    if not os.path.exists(os.path.join(d, "tasks.jsonl")):
        return None
    T = [json.loads(l) for l in open(os.path.join(d, "tasks.jsonl"))]
    M = [json.loads(l) for l in open(os.path.join(d, "metrics.jsonl"))] if os.path.exists(os.path.join(d, "metrics.jsonl")) else []
    ts = np.array([t["task_s"] for t in T])
    kv = [m.get("vllm:kv_cache_usage_perc") for m in M if m.get("vllm:kv_cache_usage_perc") is not None]
    dif = lambda k: (M[-1].get(k, 0) - M[0].get(k, 0)) if len(M) > 1 else float("nan")  # noqa: E731
    q, h = dif("vllm:prefix_cache_queries"), dif("vllm:prefix_cache_hits")
    return dict(n=len(T), turns=float(np.mean([t["turns"] for t in T])), p50=float(np.percentile(ts, 50)),
                p95=float(np.percentile(ts, 95)), acc=float(np.mean([t["correct"] for t in T])),
                prompt=float(np.mean([t["prompt_tokens"] for t in T])),
                kv_mean=float(np.mean(kv)) if kv else float("nan"), kv_max=float(np.max(kv)) if kv else float("nan"),
                kv_p95=float(np.percentile(kv, 95)) if kv else float("nan"),
                preempt=dif("vllm:num_preemptions"), hit=(h / q if q else float("nan")),
                waiting=float(np.mean([m.get("vllm:num_requests_waiting", 0) for m in M])) if M else float("nan"),
                wall=float(sum(ts)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--on", required=True); ap.add_argument("--off", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = {pc: {(arm, c): cell(os.path.join(d, f"{arm}_c{c}")) for arm in ARMS for c in CONCS}
         for pc, d in (("on", a.on), ("off", a.off))}
    L = ["# D2 step 6: concurrency sweep (300 questions, frozen agent 220001e)", "",
         "| caching | arm | c | turns | p50 s | p95 s | acc | prompt tok/task | KV mean / p95 / max | preemptions | prefix hit | waiting |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for pc in ("on", "off"):
        for c in CONCS:
            for arm in ARMS:
                x = R[pc][(arm, c)]
                if not x:
                    L.append(f"| {pc} | {arm} | {c} | (missing) |||||||||"); continue
                L.append(f"| {pc} | {arm} | {c} | {x['turns']:.2f} | {x['p50']:.2f} | {x['p95']:.2f} | {100 * x['acc']:.1f}% | "
                         f"{x['prompt']:.0f} | {100 * x['kv_mean']:.0f}% / {100 * x['kv_p95']:.0f}% / {100 * x['kv_max']:.0f}% | "
                         f"{x['preempt']:.0f} | {100 * x['hit']:.1f}% | {x['waiting']:.1f} |")
    L += ["", "## Predictions and rule H (PLAN §2d)", ""]
    out = {"cells": {f"{pc}|{k[0]}|{k[1]}": v for pc in R for k, v in R[pc].items()}}
    ok = lambda pc, arm, c: R[pc].get((arm, c)) is not None  # noqa: E731
    # P1: caching on, no arm reaches its limit by 64
    p1 = [(arm, c) for arm in ARMS for c in CONCS if ok("on", arm, c) and (R["on"][(arm, c)]["preempt"] > 0 or R["on"][(arm, c)]["kv_max"] >= 0.90)]
    L.append(f"1. Caching on, no preemptions and KV < 90% everywhere: {'MET' if not p1 else 'NOT MET'} (violations: {p1 or 'none'})")
    # P2: caching off, full over limit at 32 and 64; others below at <=64
    p2a = all(ok("off", "full", c) and R["off"][("full", c)]["preempt"] > 0 and R["off"][("full", c)]["kv_max"] >= 0.98 for c in (32, 64))
    p2b = ok("off", "full", 64) and ok("on", "full", 64) and R["off"][("full", 64)]["p95"] >= 2 * R["on"][("full", 64)]["p95"]
    p2c = [(arm, c) for arm in ("explore", "lexical", "oracle") for c in CONCS if ok("off", arm, c) and R["off"][(arm, c)]["preempt"] > 0]
    L.append(f"2. Caching off: full over its limit at 32 and 64 (preemptions > 0 and KV ≥ 98%): {'MET' if p2a else 'NOT MET'}; "
             f"full p95 at 64 off ≥ 2× on: {'MET' if p2b else 'NOT MET'}; other arms preempting: {p2c or 'none'}")
    # P3: cost of caching off at c=8
    r3 = {arm: R["off"][(arm, 8)]["p50"] / R["on"][(arm, 8)]["p50"] for arm in ARMS if ok("off", arm, 8) and ok("on", arm, 8)}
    p3 = r3.get("full", 0) >= 1.3 and all(r3.get(a_, 9) <= 1.15 for a_ in ("explore", "lexical", "oracle"))
    L.append(f"3. Caching off at c = 8, p50 ratio off/on: " + ", ".join(f"{k} {v:.2f}" for k, v in r3.items()) +
             f" → {'MET' if p3 else 'NOT MET'} (full ≥ 1.30, others ≤ 1.15)")
    # Rule H
    hs = []
    for c in (32, 64):
        e, l_, o = (R["on"].get((k, c)) for k in ("explore", "lexical", "oracle"))
        if not (e and l_ and o):
            hs.append(False); L.append(f"   - c = {c}: missing cells"); continue
        ret = (e["turns"] - l_["turns"]) / (e["turns"] - o["turns"]) if e["turns"] != o["turns"] else float("nan")
        good = ret >= 0.60 and l_["p95"] <= e["p95"]
        hs.append(good)
        L.append(f"   - c = {c}: lexical retention {ret:.2f} (≥ 0.60), p95 {l_['p95']:.2f} vs explore {e['p95']:.2f} (≤) → {'holds' if good else 'fails'}; "
                 f"acc lexical {100 * l_['acc']:.1f}% vs full {100 * R['on'][('full', c)]['acc']:.1f}% (reported)")
    H = all(hs)
    L.insert(len(L) - len(hs), f"4. **Rule H (caching on, c = 32 and 64): {'HOLDS' if H else 'DOES NOT HOLD'}**")
    if ok("off", "full", 64) and ok("off", "lexical", 64):
        rr = R["off"][("full", 64)]["p95"] / R["off"][("lexical", 64)]["p95"]
        L.append(f"   - Extra: caching off, c = 64, full p95 / lexical p95 = {rr:.2f} (predicted ≥ 1.5)")
    out.update(P1=not p1, P2=p2a, P2b=p2b, P3=p3, H=H)
    open(a.out, "w").write("\n".join(L) + "\n")
    json.dump(out, open(a.out.replace(".md", ".json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
