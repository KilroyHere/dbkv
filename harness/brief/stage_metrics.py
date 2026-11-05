"""Stage A / Stage B metrics for brief-aware prompting (Nov 5).

  python harness/brief/stage_metrics.py --run NAME=DIR[@BRIEFS.jsonl] ... [--ref NAME] [--gate] --out results/x.md

Per run: turns, p50/p95 task time, accuracy (and paired difference vs --ref), no-SQL rate, mean prompt
tokens per task, describe_table calls per task (all, and on tables already in the brief), nudged
(no-tool prose) turns per task, and turns after the first successful execute_sql.
--gate applies the Stage A gate: describe-on-brief <= 0.3/task, no-SQL < 5%, accuracy >= ref - 3 points.
"""
import argparse, json, math, os, re

import numpy as np

PRAGMA = re.compile(r'PRAGMA table_info\("((?:[^"]|"")*)"\)')


def metrics(d, briefs):
    T = {t["qid"]: t for t in (json.loads(l) for l in open(os.path.join(d, "tasks.jsonl")))}
    U = [json.loads(l) for l in open(os.path.join(d, "turns.jsonl"))]
    B = {}
    if briefs:
        B = {json.loads(l)["qid"]: {t.lower() for t in json.loads(l)["tables"]} for l in open(briefs)}
    desc_all, desc_brief, nudged, after = {}, {}, {}, {}
    by_q = {}
    for u in U:
        by_q.setdefault(u["qid"], []).append(u)
    for q, us in by_q.items():
        us.sort(key=lambda u: u.get("turn", 0))
        first_ok = None
        for u in us:
            if u.get("nudged"):
                nudged[q] = nudged.get(q, 0) + 1
            for c in u.get("tools", []):
                if c["name"] == "describe_table":
                    desc_all[q] = desc_all.get(q, 0) + 1
                    m = PRAGMA.search(c.get("sql") or "")
                    if m and m.group(1).replace('""', '"').lower() in B.get(q, set()):
                        desc_brief[q] = desc_brief.get(q, 0) + 1
                if c["name"] == "execute_sql" and not c.get("error") and first_ok is None:
                    first_ok = u["turn"]
        after[q] = (max(u.get("turn", 0) for u in us) - first_ok) if first_ok is not None else 0
    n = len(T); ts = np.array([t["task_s"] for t in T.values()])
    return T, dict(n=n, turns=float(np.mean([t["turns"] for t in T.values()])),
                   p50=float(np.percentile(ts, 50)), p95=float(np.percentile(ts, 95)),
                   acc=float(np.mean([t["correct"] for t in T.values()])),
                   nosql=float(np.mean([t["status"] != "answered" for t in T.values()])),
                   prompt=float(np.mean([t["prompt_tokens"] for t in T.values()])),
                   describe=sum(desc_all.values()) / n, describe_brief=sum(desc_brief.values()) / n,
                   nudged=sum(nudged.values()) / n, after_first_ok=float(np.mean([after.get(q, 0) for q in T])))


def paired(a, b):
    q = sorted(set(a) & set(b))
    d = np.array([float(a[i]["correct"]) - float(b[i]["correct"]) for i in q])
    return float(d.mean()), float(d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 1 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="NAME=DIR[@BRIEFS]")
    ap.add_argument("--ref", default="")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--title", default="Brief-aware prompting")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = {}
    for spec in a.run:
        name, rest = spec.split("=", 1)
        d, _, b = rest.partition("@")
        R[name] = metrics(d, b or None)
    ref = R.get(a.ref)
    L = [f"# {a.title}", "",
         "| run | n | turns | p50 s | p95 s | accuracy | Δacc vs ref (paired SE) | no-SQL | prompt tok/task | describe/task | describe on brief tables/task | nudged turns/task | turns after 1st OK SQL |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    out = {}
    for k, (T, m) in R.items():
        dd, se = paired(T, ref[0]) if ref else (float("nan"), float("nan"))
        m["dacc_ref"], m["dacc_se"] = dd, se
        out[k] = m
        L.append(f"| {k} | {m['n']} | {m['turns']:.2f} | {m['p50']:.2f} | {m['p95']:.2f} | {100 * m['acc']:.1f}% | "
                 f"{100 * dd:+.1f} ({100 * se:.1f}) | {100 * m['nosql']:.1f}% | {m['prompt']:.0f} | {m['describe']:.2f} | "
                 f"{m['describe_brief']:.2f} | {m['nudged']:.2f} | {m['after_first_ok']:.2f} |")
    if a.gate:
        L += ["", f"## Stage A gate (vs {a.ref}): describe-on-brief ≤ 0.3/task, no-SQL < 5%, accuracy ≥ ref − 3 points", ""]
        passing = []
        for k, m in out.items():
            if k == a.ref:
                continue
            g = (m["describe_brief"] <= 0.3, m["nosql"] < 0.05, 100 * m["dacc_ref"] >= -3.0)
            m["gate"] = all(g)
            if all(g):
                passing.append(k)
            L.append(f"- **{k}**: describe-on-brief {m['describe_brief']:.2f} ({'ok' if g[0] else 'FAIL'}), no-SQL "
                     f"{100 * m['nosql']:.1f}% ({'ok' if g[1] else 'FAIL'}), Δacc {100 * m['dacc_ref']:+.1f} "
                     f"({'ok' if g[2] else 'FAIL'}) → **{'PASS' if all(g) else 'FAIL'}**")
        best = max(passing, key=lambda k: out[k]["acc"]) if passing else None
        L += ["", f"**Stage A: {'PASS, pick ' + best if best else 'FAIL (neither passes)'}**"]
        out["_pick"] = best
    open(a.out, "w").write("\n".join(L) + "\n")
    json.dump(out, open(a.out.replace(".md", ".json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
