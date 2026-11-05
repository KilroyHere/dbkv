"""Stage 1.3 analysis (docs/EXPERT.md): arms (a) base, (b) few-shot, (d) write_sql expert, per brief and pooled.

  python harness/expert/stage1.py --root $DBKV_DATA/runs/expert/<job> --out results/expert_stage1.md

Expects run dirs <root>/<arm>_<brief> for arm in a,b,d and brief in full,oracle.
"""
import argparse, json, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage0 import analyze, load  # noqa: E402

ARMS = {"a": "(a) base", "b": "(b) +3 few-shot", "d": "(d) write_sql expert"}
BRIEFS = ("full", "oracle")


def adapter(d):
    p = os.path.join(d, "adapter_calls.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def run_stats(d):
    tasks, turns = load(d)
    ad = adapter(d)
    s = analyze(tasks, turns)
    ok = [t for t in turns if "turn" in t and "error" not in t]
    ts = np.array([t["task_s"] for t in tasks])
    n = len(tasks)
    agent_out = sum(t.get("output_tokens") or 0 for t in ok)
    agent_pre = sum((t.get("prompt_tokens") or 0) - (t.get("cached_tokens") or 0) for t in ok)
    ad_out = sum(r.get("output_tokens") or 0 for r in ad)
    ad_pre = sum((r.get("prompt_tokens") or 0) - (r.get("cached_tokens") or 0) for r in ad)
    prompt_all = sum(t.get("prompt_tokens") or 0 for t in ok) + sum(r.get("prompt_tokens") or 0 for r in ad)
    s.update(prompt_total=prompt_all / n, turns_per_task=s["n_turns"] / n, repair_per_task=s["repair_turns"] / n,
             adapter_calls=len(ad), adapter_calls_per_task=len(ad) / n,
             adapter_no_sql=sum(r.get("exec_error") == "expert_no_sql" for r in ad),
             adapter_exec_fail=sum(bool(r.get("exec_error")) and r.get("exec_error") != "expert_no_sql" for r in ad),
             out_agent=agent_out / n, out_adapter=ad_out / n, out_total=(agent_out + ad_out) / n,
             prefill_agent=agent_pre / n, prefill_adapter=ad_pre / n, prefill_total=(agent_pre + ad_pre) / n,
             p50=float(np.percentile(ts, 50)), p95=float(np.percentile(ts, 95)),
             acc_se=float(np.sqrt(s["acc"] * (1 - s["acc"]) / n)),
             correct={t["qid"]: bool(t["correct"]) for t in tasks}, task_s=[t["task_s"] for t in tasks],
             status={k: sum(t["status"] == k for t in tasks) for k in {t["status"] for t in tasks}})
    return s


def paired(x, y):
    """mean(x - y) and its paired SE over shared qids (x, y: {qid: bool})."""
    q = sorted(set(x) & set(y))
    d = np.array([float(x[k]) - float(y[k]) for k in q])
    return float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d))), len(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = {(arm, b): run_stats(os.path.join(a.root, f"{arm}_{b}")) for arm in ARMS for b in BRIEFS
         if os.path.isdir(os.path.join(a.root, f"{arm}_{b}"))}
    L = [f"# Expert Stage 1.3 (`{a.root}`)", "",
         "| arm | brief | acc ± SE | Δacc vs (a) ± paired SE | turns/task | repair/task | adapter calls/task | "
         "invented errs/task | output tok/task (agent + adapter) | prefill (uncached) tok/task (agent + adapter) | prompt tok/task | p50 / p95 s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (arm, b), r in R.items():
        base = R.get(("a", b))
        dd = paired(r["correct"], base["correct"]) if base and arm != "a" else None
        L.append(f"| {ARMS[arm]} | {b} | {100*r['acc']:.1f}% ± {100*r['acc_se']:.1f} | "
                 + (f"{100*dd[0]:+.1f} ± {100*dd[1]:.1f}" if dd else "—") +
                 f" | {r['turns_per_task']:.2f} | {r['repair_per_task']:.2f} | {r['adapter_calls_per_task']:.2f} | "
                 f"{r['invented_per_task']:.2f} | {r['out_total']:.0f} ({r['out_agent']:.0f} + {r['out_adapter']:.0f}) | "
                 f"{r['prefill_total']:.0f} ({r['prefill_agent']:.0f} + {r['prefill_adapter']:.0f}) | {r['prompt_total']:.0f} | {r['p50']:.2f} / {r['p95']:.2f} |")
    L += ["", "**Wrong answers by type** (no SQL → invented names → other SQL error → wrong logic):", "",
          "| arm | brief | wrong | no SQL | invented | other SQL err | wrong logic | status | adapter: no SQL / exec fail |",
          "|---|---|---|---|---|---|---|---|---|"]
    for (arm, b), r in R.items():
        w = r["wrong_types"]
        L.append(f"| {ARMS[arm]} | {b} | {r['n_wrong']} | {w.get('no_sql', 0)} | {w.get('invented_names', 0)} | "
                 f"{w.get('other_sql_error', 0)} | {w.get('wrong_logic', 0)} | {r['status']} | "
                 f"{r['adapter_no_sql']} / {r['adapter_exec_fail']} |")

    # pooled over briefs
    def P(arm):
        rs = [R[(arm, b)] for b in BRIEFS if (arm, b) in R]
        if len(rs) != len(BRIEFS):
            return None
        corr = {(b, k): v for b in BRIEFS for k, v in R[(arm, b)]["correct"].items()}
        ts = np.concatenate([R[(arm, b)]["task_s"] for b in BRIEFS])
        n = sum(r["n_tasks"] for r in rs)
        return dict(corr=corr, acc=np.mean(list(corr.values())), turns=sum(r["n_turns"] for r in rs) / n,
                    invented=sum(r["invented_per_task"] * r["n_tasks"] for r in rs) / n, p50=float(np.percentile(ts, 50)))
    pa, pb, pd = P("a"), P("b"), P("d")
    out = dict(runs={f"{k[0]}_{k[1]}": {kk: vv for kk, vv in v.items() if kk not in ("correct", "task_s")} for k, v in R.items()})
    if pa and pb and pd:
        L += ["", "**Pooled over both briefs (300 task-runs per arm)**", ""]
        for nm, p in (("a", pa), ("b", pb), ("d", pd)):
            L.append(f"- {ARMS[nm]}: acc {100*p['acc']:.1f}%, turns/task {p['turns']:.2f}, invented errs/task "
                     f"{p['invented']:.2f}, p50 {p['p50']:.2f} s")
        L += ["", "**Predictions** ((d) vs (a), same brief; per brief and pooled):", ""]
        rows = [(b, R[("d", b)], R[("a", b)]) for b in BRIEFS] + [("pooled", None, None)]
        for b, rd, ra in rows:
            if rd is None:
                dacc = paired(pd["corr"], pa["corr"]); ti, ta = pd["invented"], pa["invented"]
                tu_d, tu_a, p50d, p50a = pd["turns"], pa["turns"], pd["p50"], pa["p50"]
            else:
                dacc = paired(rd["correct"], ra["correct"]); ti, ta = rd["invented_per_task"], ra["invented_per_task"]
                tu_d, tu_a, p50d, p50a = rd["turns_per_task"], ra["turns_per_task"], rd["p50"], ra["p50"]
            inv_cut = 1 - ti / ta if ta else float("nan")
            L.append(f"- {b}: (1) Δacc {100*dacc[0]:+.1f} ± {100*dacc[1]:.1f} pts (≥ +8: {'met' if dacc[0] >= 0.08 else 'not met'}); "
                     f"(2) invented errs {ta:.2f} → {ti:.2f}, cut {100*inv_cut:.0f}% (≥ 50%: {'met' if inv_cut >= 0.5 else 'not met'}); "
                     f"(3) turns {tu_a:.2f} → {tu_d:.2f}, cut {100*(1-tu_d/tu_a):.1f}% (≥ 15%: {'met' if tu_d <= 0.85*tu_a else 'not met'}); "
                     f"(4) p50 {p50a:.2f} → {p50d:.2f} s, cut {100*(1-p50d/p50a):.1f}% (≥ 10%: {'met' if p50d <= 0.9*p50a else 'not met'})")
        verdict = True; parts = []
        for nm, px in (("a", pa), ("b", pb)):
            dacc = pd["acc"] - px["acc"]; tcut = 1 - pd["turns"] / px["turns"]
            ok = dacc >= 0.05 or tcut >= 0.10
            verdict &= ok
            parts.append(f"vs {ARMS[nm]}: Δacc {100*dacc:+.1f} pts (≥ 5?), turns cut {100*tcut:.1f}% (≥ 10%?) → {'beats' if ok else 'does not beat'}")
        L += ["", "**Stage 1 rule** (pooled): " + "; ".join(parts) +
              f" → **{'CONTINUE past Stage 1' if verdict else 'STOP after Stage 1'}**", ""]
        out["verdict_continue"] = bool(verdict)
    open(a.out, "w").write("\n".join(L) + "\n")
    json.dump(out, open(a.out.replace(".md", ".json"), "w"), indent=1, default=float)
    print("\n".join(L))


if __name__ == "__main__":
    main()
