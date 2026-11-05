"""D2 step 5 analysis, exactly as pre-registered in PLAN §2c.

  python harness/brief/analyze_d2.py --arm explore=RUN_A/explore --arm full=RUN_A/full ... --out results/d2_step5.md
"""
import argparse, json, math, os

import numpy as np

GEN = ["compact", "lexical", "llm"]


def load(d):
    tasks = {t["qid"]: t for t in (json.loads(l) for l in open(os.path.join(d, "tasks.jsonl")))}
    return tasks


def stats(t):
    ts = np.array([x["task_s"] for x in t.values()])
    return dict(n=len(t), turns=float(np.mean([x["turns"] for x in t.values()])),
                p50=float(np.percentile(ts, 50)), p95=float(np.percentile(ts, 95)),
                acc=float(np.mean([x["correct"] for x in t.values()])),
                prompt=float(np.mean([x["prompt_tokens"] for x in t.values()])),
                build_p50=float(np.median([x.get("build_s", 0.0) for x in t.values()])),
                nosql=float(np.mean([x["status"] != "answered" for x in t.values()])))


def paired(a, b):
    """acc_a - acc_b over shared questions, with paired SE."""
    q = sorted(set(a) & set(b))
    d = np.array([float(a[i]["correct"]) - float(b[i]["correct"]) for i in q])
    return float(d.mean()), float(d.std(ddof=1) / math.sqrt(len(d))), len(q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True, help="name=dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    runs = {k: load(v) for k, v in (x.split("=", 1) for x in a.arm)}
    S = {k: stats(v) for k, v in runs.items()}
    ex, fu, orc = S["explore"], S["full"], S["oracle"]
    lines = ["# D2 step 5: brief arms on BIRD dev (frozen agent 220001e, concurrency 8)", "",
             "| arm | n | turns | p50 s | p95 s | accuracy | Δacc vs full (paired SE) | Δacc vs explore (paired SE) | prompt tok/task | no-SQL | build p50 s |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in ["explore", "full", "compact", "lexical", "llm", "oracle"]:
        if k not in S:
            continue
        s = S[k]
        df, sf, _ = paired(runs[k], runs["full"]); de, se, _ = paired(runs[k], runs["explore"])
        lines.append(f"| {k} | {s['n']} | {s['turns']:.2f} | {s['p50']:.2f} | {s['p95']:.2f} | {100 * s['acc']:.1f}% | "
                     f"{100 * df:+.1f} ({100 * sf:.1f}) | {100 * de:+.1f} ({100 * se:.1f}) | {s['prompt']:.0f} | "
                     f"{100 * s['nosql']:.1f}% | {s['build_p50']:.2f} |")
    lines += ["", "## Rules (PLAN §2c)", ""]
    out = {"stats": S, "arms": {}}
    any_yes = False
    for k in GEN:
        if k not in S:
            continue
        s = S[k]
        ret = (ex["turns"] - s["turns"]) / (ex["turns"] - orc["turns"])
        dacc, se, _ = paired(runs[k], runs["full"])
        r1a, r1b, r1c = ret >= 0.60, 100 * dacc >= -2.0, s["p95"] <= ex["p95"]
        r2 = s["prompt"] <= 0.5 * fu["prompt"]
        r1 = r1a and r1b and r1c
        any_yes |= r1 and r2
        out["arms"][k] = dict(retention=ret, dacc_full=dacc, dacc_se=se, R1=r1, R2=r2, R1_parts=[r1a, r1b, r1c])
        lines.append(f"- **{k}**: retention {ret:.2f} (≥ 0.60: {'yes' if r1a else 'no'}); Δacc vs full "
                     f"{100 * dacc:+.1f} ± {100 * se:.1f} (≥ −2.0: {'yes' if r1b else 'no'}); p95 {s['p95']:.2f} vs explore "
                     f"{ex['p95']:.2f} (≤: {'yes' if r1c else 'no'}) → **R1 {'PASS' if r1 else 'FAIL'}**; prompt tokens "
                     f"{s['prompt']:.0f} vs 0.5 × full = {0.5 * fu['prompt']:.0f} → **R2 {'PASS' if r2 else 'FAIL'}**")
    passing = [k for k, v in out["arms"].items() if v["R1"] and v["R2"]]
    lines += ["", f"**Research question at concurrency 8: {'YES' if any_yes else 'NO'}** "
                  f"(arms passing R1 and R2: {', '.join(passing) or 'none'})."]
    out["answer"] = any_yes; out["passing"] = passing
    open(a.out, "w").write("\n".join(lines) + "\n")
    json.dump(out, open(a.out.replace(".md", ".json"), "w"), indent=1)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
