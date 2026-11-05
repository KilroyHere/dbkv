"""Tests 2 and 3 analysis, exactly as pre-registered in PLAN §2b.

  python harness/agent/analyze.py t2 --c1 RUN/c1_none --c8 RUN/c8_none --out results/t2_summary.md
  python harness/agent/analyze.py t3 --a RUN2/c8_none --b RUN3/c8_full --c RUN3/c8_oracle --out results/t3_summary.md
"""
import argparse, json, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools import EXPLORE  # noqa: E402


def load(d):
    tasks = [json.loads(l) for l in open(os.path.join(d, "tasks.jsonl"))]
    turns = [json.loads(l) for l in open(os.path.join(d, "turns.jsonl"))]
    return tasks, turns


def canon(sql):
    try:
        import sqlglot
        return sqlglot.parse_one(sql, read="sqlite").sql(dialect="sqlite", normalize=True)
    except Exception:  # noqa: BLE001
        return " ".join(sql.lower().split())


def explore_share(turns):
    tool_turns = [t for t in turns if t.get("tools")]
    all_turns = [t for t in turns if "turn" in t and "error" not in t]
    exp_turns = [t for t in tool_turns if all(c["name"] in EXPLORE for c in t["tools"])]
    calls = [c for t in tool_turns for c in t["tools"]]
    return (len(exp_turns) / len(all_turns) if all_turns else np.nan,
            sum(c["name"] in EXPLORE for c in calls) / len(calls) if calls else np.nan)


def repeats(turns):
    """Share of DB time from repeated SQL: exact / canonical, within a task / across tasks on the same DB."""
    order = sorted((t for t in turns if t.get("tools")), key=lambda t: (t["qid"], t["turn"]))
    total = 0.0
    rep = {k: 0.0 for k in ("exact_within", "canon_within", "exact_across", "canon_across")}
    seen_task, seen_db = {}, {}
    for t in order:
        for c in t["tools"]:
            if not c.get("sql"):
                continue
            rt = c["runtime_s"]; total += rt
            for kind, key in (("exact", c["sql"].strip()), ("canon", canon(c["sql"]))):
                st = seen_task.setdefault((t["qid"], kind), set()); sd = seen_db.setdefault((t["db"], kind), set())
                if key in st:
                    rep[kind + "_within"] += rt
                if key in sd:
                    rep[kind + "_across"] += rt
                st.add(key); sd.add(key)
    return {k: (v / total if total else np.nan) for k, v in rep.items()}, total


def time_breakdown(tasks, turns):
    q = sum((t.get("queue_ms") or 0) for t in turns) / 1000
    pf = sum((t.get("prefill_ms") or 0) for t in turns) / 1000
    dc = sum((t.get("decode_ms") or 0) for t in turns) / 1000
    cl = sum(t.get("client_s", 0) for t in turns)
    db = sum(t["db_s"] for t in tasks); tot = sum(t["task_s"] for t in tasks)
    return dict(task_s=tot, db=db / tot, queue=q / tot, prefill=pf / tot, decode=dc / tot,
                llm_other=(cl - q - pf - dc) / tot, rest=(tot - cl - db) / tot)


def summarize_run(name, tasks, turns):
    ts = np.array([t["task_s"] for t in tasks]); acc = np.mean([t["correct"] for t in tasks])
    tb = time_breakdown(tasks, turns); es, ec = explore_share(turns); rp, dbt = repeats(turns)
    p90 = np.percentile(ts, 90); slow = [t for t in tasks if t["task_s"] > p90]
    slow_wrong = 1 - np.mean([t["correct"] for t in slow]) if slow else np.nan
    errs = {}
    for t in turns:
        for c in t.get("tools", []):
            if c.get("error"):
                errs[c["error"]] = errs.get(c["error"], 0) + 1
    status = {}
    for t in tasks:
        status[t["status"]] = status.get(t["status"], 0) + 1
    return dict(name=name, n=len(tasks), acc=acc, acc_se=np.sqrt(acc * (1 - acc) / len(tasks)),
                turns=np.mean([t["turns"] for t in tasks]), p50=np.percentile(ts, 50), p95=np.percentile(ts, 95),
                p90=p90, slow_n=len(slow), slow_wrong=slow_wrong, explore_turn_share=es, explore_call_share=ec,
                prompt_tokens=np.mean([t["prompt_tokens"] for t in tasks]), repeats=rp, db_total_s=dbt,
                breakdown=tb, tool_errors=errs, status=status)


def fmt_run(r):
    b = r["breakdown"]; rp = r["repeats"]
    return [f"### {r['name']} (n = {r['n']})", "",
            f"- accuracy {100 * r['acc']:.1f}% ± {100 * r['acc_se']:.1f} (SE); mean turns {r['turns']:.2f}; "
            f"task time p50 {r['p50']:.2f} s, p90 {r['p90']:.2f} s, p95 {r['p95']:.2f} s; mean prompt tokens/task {r['prompt_tokens']:.0f}",
            f"- time shares of Σ task time ({b['task_s']:.0f} s): **DB {100 * b['db']:.1f}%**, LLM queue {100 * b['queue']:.1f}%, "
            f"prefill {100 * b['prefill']:.1f}%, decode {100 * b['decode']:.1f}%, other LLM-call {100 * b['llm_other']:.1f}%, "
            f"agent/other {100 * b['rest']:.1f}%",
            f"- tasks above p90 ({r['slow_n']}): **{100 * r['slow_wrong']:.0f}% wrong**",
            f"- exploring: {100 * r['explore_turn_share']:.1f}% of turns (all tool calls are exploration tools), "
            f"{100 * r['explore_call_share']:.1f}% of tool calls",
            f"- DB time from repeated SQL (total DB {r['db_total_s']:.1f} s): exact within-task {100 * rp['exact_within']:.1f}%, "
            f"canonical within-task {100 * rp['canon_within']:.1f}%, exact across tasks (same DB) {100 * rp['exact_across']:.1f}%, "
            f"canonical across {100 * rp['canon_across']:.1f}%",
            f"- task status {r['status']}; tool errors {r['tool_errors']}", ""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("test", choices=["t2", "t3"])
    ap.add_argument("--c1"); ap.add_argument("--c8")
    ap.add_argument("--a"); ap.add_argument("--b"); ap.add_argument("--c")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {}
    if a.test == "t2":
        r1 = summarize_run("concurrency 1", *load(a.c1)); r8 = summarize_run("concurrency 8", *load(a.c8))
        db = r1["breakdown"]["db"]; sw = r1["slow_wrong"]
        v_db = "broker + result caching COME BACK" if db >= 0.40 else "DROP broker + result caching"
        v_d4 = "PURSUE D4 early stopping" if sw >= 0.60 else ("DROP D4" if sw < 0.40 else "INCONCLUSIVE (40–60%)")
        lines = ["# Test 2: real SQL-agent traces (BIRD dev, 150 tasks, seed 0)", "",
                 f"**Rule DB** (concurrency 1): DB share = {100 * db:.1f}% (≥ 40% means come back) → **{v_db}**", "",
                 f"**Rule D4** (concurrency 1): {100 * sw:.0f}% of the {r1['slow_n']} tasks above p90 are wrong "
                 f"(≥ 60% pursue, < 40% drop) → **{v_d4}**", ""] + fmt_run(r1) + fmt_run(r8)
        out = dict(db_share=db, slow_wrong=sw, verdict_db=v_db, verdict_d4=v_d4, c1=r1, c8=r8)
    else:
        ra = summarize_run("(a) plain exploration", *load(a.a))
        rb = summarize_run("(b) full schema + 3 samples", *load(a.b))
        rc = summarize_run("(c) oracle brief (gold tables/columns)", *load(a.c))
        c1 = ra["explore_turn_share"] >= 0.30
        c2 = rc["turns"] <= 0.75 * ra["turns"]
        c3 = rb["p50"] > 1.05 * rc["p50"]
        verdict = "PURSUE D2" if (c1 and c2 and c3) else "DROP D2"
        lines = ["# Test 3: D2 pilot, schema brief (concurrency 8, 150 tasks)", "",
                 "| arm | turns/task | p50 task s | p95 task s | accuracy ± SE | prompt tokens/task | explore turns |",
                 "|---|---|---|---|---|---|---|"]
        for r in (ra, rb, rc):
            lines.append(f"| {r['name']} | {r['turns']:.2f} | {r['p50']:.2f} | {r['p95']:.2f} | "
                         f"{100 * r['acc']:.1f}% ± {100 * r['acc_se']:.1f} | {r['prompt_tokens']:.0f} | {100 * r['explore_turn_share']:.1f}% |")
        lines += ["", "**Rule** (all three needed to pursue):",
                  f"1. explore share (a) = {100 * ra['explore_turn_share']:.1f}% ≥ 30%: {'yes' if c1 else 'no'}",
                  f"2. turns (c) = {rc['turns']:.2f} ≤ 0.75 × (a) = {0.75 * ra['turns']:.2f}: {'yes' if c2 else 'no'} "
                  f"(cut {100 * (1 - rc['turns'] / ra['turns']):.1f}%)",
                  f"3. p50 (b) = {rb['p50']:.2f} s > 1.05 × p50 (c) = {1.05 * rc['p50']:.2f} s: {'yes' if c3 else 'no'}",
                  "", f"**→ {verdict}**", ""] + fmt_run(ra) + fmt_run(rb) + fmt_run(rc)
        out = dict(verdict=verdict, conditions=[c1, c2, c3], a=ra, b=rb, c=rc)
    open(a.out, "w").write("\n".join(lines) + "\n")
    json.dump(out, open(a.out.replace(".md", ".json"), "w"), indent=1, default=float)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
