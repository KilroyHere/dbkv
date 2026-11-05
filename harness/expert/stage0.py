"""Stage 0 of the SQL-expert test (docs/EXPERT.md): how much of the agent's work is failed SQL + repair, and why
wrong answers are wrong. Reads existing traces only (no GPU, no DB re-execution).

  python harness/expert/stage0.py --run NAME=DIR [...] --judge NAME,NAME --out results/expert_stage0.md

Definitions are the pre-registered ones in docs/EXPERT.md.
"""
import argparse, json, os
from collections import Counter, defaultdict

INVENTED = ("no_such_table", "no_such_column")


def load(d):
    tasks = [json.loads(l) for l in open(os.path.join(d, "tasks.jsonl"))]
    turns = [json.loads(l) for l in open(os.path.join(d, "turns.jsonl"))]
    return tasks, turns


def err_class(msg):
    if not msg:
        return None
    m = msg.lower()
    if "no such column" in m:
        return "no_such_column"
    if "no such table" in m:
        return "no_such_table"
    if "syntax error" in m:
        return "syntax"
    if "interrupted" in m:
        return "timeout"
    return "other"


def analyze(tasks, turns):
    by_task = defaultdict(list)
    for t in turns:
        if "turn" in t and "error" not in t:  # skip llm_error rows
            by_task[t["qid"]].append(t)
    n_turns = 0; failed = repair = union = 0
    dec_all = dec_failed = dec_repair = dec_union = 0.0
    out_all = out_union = 0
    invented_calls = 0; fail_classes = Counter()
    task_invented = Counter()
    for qid, ts in by_task.items():
        ts.sort(key=lambda r: r["turn"])
        prev_failed = False
        for r in ts:
            fcalls = [c for c in r.get("tools", []) if c["name"] in ("execute_sql", "write_sql") and c.get("error")]
            for c in fcalls:
                fail_classes[c["error"]] += 1
                if c["error"] in INVENTED:
                    invented_calls += 1; task_invented[qid] += 1
            is_f = bool(fcalls); is_r = prev_failed
            d = (r.get("decode_ms") or 0) / 1000; o = r.get("output_tokens") or 0
            n_turns += 1; dec_all += d; out_all += o
            if is_f:
                failed += 1; dec_failed += d
            if is_r:
                repair += 1; dec_repair += d
            if is_f or is_r:
                union += 1; dec_union += d; out_union += o
            prev_failed = is_f
    # wrong-answer types (pre-registered order)
    types = Counter(); wrong_logic_with_invented = 0; wrong_no_block = 0
    for t in tasks:
        if t["correct"]:
            continue
        ec = err_class(t.get("pred_error")) if t.get("pred_error") != "gold_error" else "gold_error"
        if not t.get("pred_sql"):
            ty = "no_sql"
        elif ec in INVENTED:
            ty = "invented_names"
        elif ec is not None:
            ty = "other_sql_error"
        else:
            ty = "wrong_logic"
            if task_invented[t["qid"]]:
                wrong_logic_with_invented += 1
        if ec in INVENTED:
            task_invented[t["qid"]] += 1  # graded SQL counts as an invented-name error too
        if t.get("status") != "answered":
            wrong_no_block += 1
        types[ty] += 1
    n_wrong = sum(types.values())
    sql_writing = types["invented_names"] + types["other_sql_error"] + types["wrong_logic"]
    return dict(n_tasks=len(tasks), acc=sum(t["correct"] for t in tasks) / len(tasks), n_turns=n_turns,
                failed_turns=failed, repair_turns=repair, union_turns=union,
                failed_share=failed / n_turns, repair_share=repair / n_turns, union_share=union / n_turns,
                decode_s=dec_all, decode_failed_share=dec_failed / dec_all, decode_repair_share=dec_repair / dec_all,
                decode_union_share=dec_union / dec_all, output_union_share=out_union / out_all,
                failed_sql_calls=dict(fail_classes), invented_calls=invented_calls,
                invented_per_task=sum(task_invented.values()) / len(tasks),
                n_wrong=n_wrong, wrong_types=dict(types), wrong_logic_with_invented=wrong_logic_with_invented,
                wrong_without_sql_block=wrong_no_block,
                sql_writing_wrong=sql_writing, sql_writing_share=sql_writing / n_wrong if n_wrong else float("nan"))


def pooled(rs):
    s = lambda k: sum(r[k] for r in rs)
    tw = Counter()
    for r in rs:
        tw.update(r["wrong_types"])
    return dict(repair_share=s("repair_turns") / s("n_turns"), union_share=s("union_turns") / s("n_turns"),
                sql_writing_share=s("sql_writing_wrong") / s("n_wrong"), n_wrong=s("n_wrong"), wrong_types=dict(tw))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="NAME=DIR")
    ap.add_argument("--judge", required=True, help="comma-separated run names the stop rule is judged on (pooled)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    runs = {}
    for spec in a.run:
        name, d = spec.rsplit("=", 1)
        runs[name] = dict(analyze(*load(d)), dir=d)
    L = ["# Expert Stage 0: failed SQL + repair turns, and wrong-answer types (existing traces)", "",
         "Definitions: docs/EXPERT.md (pre-registered). *Failed* = turn issuing a failed `execute_sql`; *repair* = the "
         "turn right after one; *union* = either.", "",
         "| arm | n | acc | turns | failed-SQL turns | repair turns | failed ∪ repair | decode s in failed / repair / ∪ | invented-name errs / task |",
         "|---|---|---|---|---|---|---|---|---|"]
    for k, r in runs.items():
        L.append(f"| {k} | {r['n_tasks']} | {100*r['acc']:.1f}% | {r['n_turns']} | {100*r['failed_share']:.1f}% | "
                 f"**{100*r['repair_share']:.1f}%** | {100*r['union_share']:.1f}% | "
                 f"{100*r['decode_failed_share']:.1f}% / {100*r['decode_repair_share']:.1f}% / {100*r['decode_union_share']:.1f}% | "
                 f"{r['invented_per_task']:.2f} |")
    L += ["", "**Wrong answers by type** (no SQL → invented names → other SQL error → wrong logic, first match):", "",
          "| arm | wrong | no SQL | invented names | other SQL error | wrong logic (of which had invented-name errs earlier) | SQL-writing share | wrong w/o ```sql``` block |",
          "|---|---|---|---|---|---|---|---|"]
    for k, r in runs.items():
        w = r["wrong_types"]
        L.append(f"| {k} | {r['n_wrong']} | {w.get('no_sql', 0)} | {w.get('invented_names', 0)} | {w.get('other_sql_error', 0)} | "
                 f"{w.get('wrong_logic', 0)} ({r['wrong_logic_with_invented']}) | {100*r['sql_writing_share']:.0f}% | {r['wrong_without_sql_block']} |")
    L += ["", "Failed `execute_sql` calls by class: " + "; ".join(f"{k}: {r['failed_sql_calls']}" for k, r in runs.items()), ""]
    judged = [runs[n] for n in a.judge.split(",")]
    p = pooled(judged)
    stop = p["repair_share"] < 0.15 and p["sql_writing_share"] <= 0.50
    L += [f"**Stage 0 rule** (pooled over {a.judge}): repair turns = {100*p['repair_share']:.1f}% of turns "
          f"(stop needs < 15%: {'yes' if p['repair_share'] < 0.15 else 'no'}); SQL-writing errors = "
          f"{100*p['sql_writing_share']:.0f}% of {p['n_wrong']} wrong answers (stop needs ≤ 50%: "
          f"{'yes' if p['sql_writing_share'] <= 0.5 else 'no'}) → **{'STOP' if stop else 'CONTINUE to Stage 1'}**", ""]
    open(a.out, "w").write("\n".join(L) + "\n")
    json.dump(dict(runs=runs, pooled=p, stop=stop), open(a.out.replace(".md", ".json"), "w"), indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
