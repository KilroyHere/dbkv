"""Summarize a G3 sweep directory (slurm/g3_sweep.sbatch output) into g3_table.csv and g3_summary.md.

    python harness/g3_summarize.py $SCRATCH/dbkv/runs/g3/main [--hit-thresh 0.95] [--max-preempt 0]

Reads every */c{C}_n{N}_r*/summary.json under RUN (skipping failed_* dirs). The rep is taken from a
`rep<k>` parent directory when there is one (the sweep calls replay.py with --reps 1, so the subdir is
always *_r0), otherwise from summary["rep"]. Each metric is the mean over reps.
resume_full_hit_frac and recomputed tokens/resume are recomputed from each point's turns.csv
(turn > 0, t_req >= warmup, full hit = recomputed <= --full-hit-tokens, default 16), because
summary.json files written before the replay.py fix used < 16. Also: recomputed tokens per non-full-hit resume. Also parses vLLM's
"GPU KV cache size: N tokens" from RUN/kv_actual.txt.

Observed memory limit (per context): the largest N such that every grid point at or below it has
rep-mean resume_full_hit_frac >= --hit-thresh and preemptions <= --max-preempt in every rep
("contiguous" rule). The largest passing N regardless of gaps is also reported if it differs.

G3 kill-rule inputs (PLAN §3 + Nov 4 amendment, judged at 8k and 20k):
  (a) a limit exists below 32 sessions: the first failing N is <= 32.
  (b) recompute + re-queue share of p95 per-turn latency at each above-limit N:
        share(N) = (resume_ttft_p95(N) - resume_ttft_p95(N_min)) / turn_e2e_p95(N)
      Resume TTFT = tool return -> first token = queueing + prefill of the new + recomputed tokens;
      at the smallest N there is neither recompute nor queueing to speak of, so the excess over it is
      the time lost to recompute and re-queueing. Decode slowdown from larger batches is excluded
      (it is in e2e after the first token, not in TTFT). The kill line is share < 10%.
      Also reported: e2e inflation = turn_e2e_p95(N) / turn_e2e_p95(limit N) - 1.
"""
import argparse, csv, glob, json, math, os, re
from collections import defaultdict

PRED_LIMIT = {4096: 32.4, 8192: 16.2, 20480: 6.5}   # prediction 1a
PRED_POOL = 132_512                                  # prediction 1a KV pool, tokens (mid overhead)
KILL_N = 32
KILL_SHARE = 0.10
FULL_HIT_TOKENS = 16   # a full hit still recomputes the last partial block (<=15) + the last sampled token
METRICS = ["resume_ttft_p50", "resume_ttft_p95", "task_p50", "task_p95", "turn_e2e_p95",
           "recomputed_per_resume", "recomputed_per_miss", "resume_full_hit_frac", "kv_usage_mean", "kv_usage_max",
           "waiting_mean", "preemptions", "prefix_hit_rate", "throughput_tasks_s"]


def load(run):
    pts = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(run, "**", "summary.json"), recursive=True)):
        rel = os.path.relpath(f, run).split(os.sep)
        if any(p.startswith("failed_") for p in rel):
            continue
        s = json.load(open(f))
        rep = next((int(p[3:]) for p in rel[:-2] if re.fullmatch(r"rep\d+", p)), s.get("rep", 0))
        s["rep"] = rep
        s["recomputed_per_resume"] = s["recomputed_tokens"] / s["resume_turns"] if s.get("resume_turns") else None
        s["full_hit_source"] = "summary.json"
        s["recomputed_per_miss"] = None
        tc = os.path.join(os.path.dirname(f), "turns.csv")
        if os.path.exists(tc):   # recompute: summary.json may predate the <=16 full-hit rule
            with open(tc) as fh:
                rec = [int(t["recomputed"]) for t in csv.DictReader(fh)
                       if int(t["turn"]) > 0 and float(t["t_req"]) >= s["warmup"] and t["recomputed"] not in ("", "None")]
            if rec:
                miss = [r for r in rec if r > FULL_HIT_TOKENS]
                s["resume_full_hit_frac"] = 1 - len(miss) / len(rec)
                s["recomputed_per_resume"] = sum(rec) / len(rec)
                s["recomputed_per_miss"] = sum(miss) / len(miss) if miss else None
                s["full_hit_source"] = "turns.csv"
        s["throughput_tasks_s"] = s["tasks"] / s["duration"] if s.get("duration") else None
        pts[(s["ctx"], s["sessions"])].append(s)
    return pts


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def kv_pool(run):
    f = os.path.join(run, "kv_actual.txt")
    if not os.path.exists(f):
        return None
    vals = [int(m.replace(",", "")) for m in re.findall(r"GPU KV cache size: ([\d,]+) tokens", open(f).read())]
    return vals or None


def fmt(x, nd=3):
    if x is None:
        return "–"
    if isinstance(x, float) and math.isnan(x):
        return "–"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def main():
    global FULL_HIT_TOKENS
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--hit-thresh", type=float, default=0.95)
    ap.add_argument("--max-preempt", type=int, default=0)
    ap.add_argument("--full-hit-tokens", type=int, default=FULL_HIT_TOKENS,
                    help="a resume with recomputed <= this counts as a full prefix-cache hit")
    ap.add_argument("--out", help="output dir (default: RUN)")
    a = ap.parse_args()
    out = a.out or a.run
    FULL_HIT_TOKENS = a.full_hit_tokens
    pts = load(a.run)
    if not pts:
        raise SystemExit(f"no summary.json under {a.run}")

    rows = []
    for (c, n), ss in sorted(pts.items()):
        r = dict(ctx=c, sessions=n, reps=len(ss), rep_ids=" ".join(str(s["rep"]) for s in sorted(ss, key=lambda s: s["rep"])))
        for m in METRICS:
            r[m] = mean([s.get(m) for s in ss])
        r["preemptions_max"] = max(s.get("preemptions", 0) for s in ss)
        r["full_hit_source"] = "/".join(sorted({s["full_hit_source"] for s in ss}))
        r["passes"] = (r["resume_full_hit_frac"] is not None and r["resume_full_hit_frac"] >= a.hit_thresh
                       and r["preemptions_max"] <= a.max_preempt)
        rows.append(r)

    by_ctx = defaultdict(list)
    for r in rows:
        by_ctx[r["ctx"]].append(r)

    lim = {}
    for c, rs in by_ctx.items():
        contiguous = None
        for r in rs:                      # sorted by N
            if not r["passes"]:
                break
            contiguous = r["sessions"]
        any_pass = max((r["sessions"] for r in rs if r["passes"]), default=None)
        first_fail = next((r["sessions"] for r in rs if not r["passes"]), None)
        base = rs[0]
        lim_row = next((r for r in rs if r["sessions"] == contiguous), None)
        for r in rs:
            above = contiguous is None or r["sessions"] > contiguous
            r["above_limit"] = above
            if base["resume_ttft_p95"] is not None and r["resume_ttft_p95"] is not None and r["turn_e2e_p95"]:
                r["recompute_queue_share"] = (r["resume_ttft_p95"] - base["resume_ttft_p95"]) / r["turn_e2e_p95"]
            else:
                r["recompute_queue_share"] = None
            r["e2e_inflation_vs_limit"] = (r["turn_e2e_p95"] / lim_row["turn_e2e_p95"] - 1
                                           if lim_row and lim_row["turn_e2e_p95"] and r["turn_e2e_p95"] else None)
        lim[c] = dict(limit=contiguous, any_pass=any_pass, first_fail=first_fail, base_n=base["sessions"],
                      grid=[r["sessions"] for r in rs])

    cols = ["ctx", "sessions", "reps", "rep_ids"] + METRICS + ["preemptions_max", "passes", "above_limit", "full_hit_source",
                                                               "recompute_queue_share", "e2e_inflation_vs_limit"]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "g3_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items() if k in cols})

    pool = kv_pool(a.run)
    L = []
    L.append(f"# G3 summary: `{os.path.abspath(a.run)}`\n")
    L.append(f"{sum(r['reps'] for r in rows)} runs over {len(rows)} (ctx, N) points; metrics are means over reps.\n")
    L.append(f"**Limit rule:** observed limit = largest N such that every grid N' <= N has rep-mean "
             f"resume_full_hit_frac >= {a.hit_thresh} and preemptions <= {a.max_preempt} in every rep.\n")
    L.append(f"Resume turns in the measured window (turn > 0, t_req >= warmup) are full hits when recomputed <= "
             f"{FULL_HIT_TOKENS} tokens; full-hit fraction and recomputed tokens are recomputed from turns.csv "
             f"(not summary.json). recomp/miss = mean recomputed tokens over resumes that were not full hits "
             f"(mean over reps that had any).\n")
    L.append("## Per point\n")
    hdr = ["ctx", "N", "reps", "TTFT p50", "TTFT p95", "task p50", "task p95", "e2e p95", "recomp/resume",
           "recomp/miss", "full hit", "KV mean", "KV max", "waiting", "preempt", "prefix hit", "tasks/s", "pass", "rq share"]
    L.append("| " + " | ".join(hdr) + " |")
    L.append("|" + "---|" * len(hdr))
    for r in rows:
        L.append("| " + " | ".join([str(r["ctx"]), str(r["sessions"]), str(r["reps"]),
                 fmt(r["resume_ttft_p50"]), fmt(r["resume_ttft_p95"]), fmt(r["task_p50"], 1), fmt(r["task_p95"], 1),
                 fmt(r["turn_e2e_p95"]), fmt(r["recomputed_per_resume"], 0), fmt(r["recomputed_per_miss"], 0), fmt(r["resume_full_hit_frac"]),
                 fmt(r["kv_usage_mean"]), fmt(r["kv_usage_max"]), fmt(r["waiting_mean"], 1),
                 fmt(r["preemptions"], 1), fmt(r["prefix_hit_rate"]), fmt(r["throughput_tasks_s"]),
                 "yes" if r["passes"] else "no", fmt(r["recompute_queue_share"])]) + " |")

    L.append("\n## Prediction 1a\n")
    if pool:
        p = pool[0]
        same = "" if len(set(pool)) == 1 else f" (server starts disagree: {sorted(set(pool))})"
        L.append(f"- KV pool: predicted {PRED_POOL:,} tokens; vLLM reported {p:,}{same} "
                 f"({(p / PRED_POOL - 1) * 100:+.1f}%).")
    else:
        p = None
        L.append(f"- KV pool: predicted {PRED_POOL:,} tokens; `kv_actual.txt` missing or unparsable.")
    L.append("\n| ctx | predicted limit | pool / ctx (vLLM pool) | observed limit | first failing N | largest passing N | grid |")
    L.append("|---|---|---|---|---|---|---|")
    for c in sorted(lim):
        d = lim[c]
        L.append(f"| {c} | {PRED_LIMIT.get(c, '–')} | {fmt(p / c, 1) if p else '–'} | "
                 f"{d['limit'] if d['limit'] is not None else '< ' + str(d['grid'][0])} | "
                 f"{d['first_fail'] if d['first_fail'] is not None else 'none (> ' + str(d['grid'][-1]) + ')'} | "
                 f"{d['any_pass']} | {' '.join(map(str, d['grid']))} |")
    L.append("\nThe true limit lies between the observed limit and the first failing N (grid resolution).")

    L.append("\n## G3 kill-rule inputs (judged at 8k and 20k, per the Nov 4 amendment)\n")
    L.append(f"- **(a) Limit below {KILL_N} sessions:** kill if no limit appears at N <= {KILL_N}.")
    for c in sorted(lim):
        d = lim[c]
        ff = d["first_fail"]
        verdict = (f"yes (first failure at N={ff})" if ff is not None and ff <= KILL_N
                   else "no (no failure in grid)" if ff is None else f"no (first failure at N={ff} > {KILL_N})")
        tag = "" if c in (8192, 20480) else " *(reported, not judged)*"
        L.append(f"  - {c}: {verdict}{tag}")
    L.append(f"- **(b) Recompute + re-queue share of p95 per-turn latency:** kill if < {KILL_SHARE:.0%}.")
    L.append("  share(N) = (resume TTFT p95(N) - resume TTFT p95(N_min)) / turn e2e p95(N); "
             "e2e infl. = turn e2e p95(N) / turn e2e p95(at limit) - 1.")
    for c in sorted(lim):
        tag = "" if c in (8192, 20480) else " *(reported, not judged)*"
        ab = [r for r in by_ctx[c] if r["above_limit"]]
        if not ab:
            L.append(f"  - {c}: no above-limit points{tag}")
            continue
        parts = [f"N={r['sessions']}: {fmt(r['recompute_queue_share'])} (e2e infl. {fmt(r['e2e_inflation_vs_limit'], 2)})"
                 for r in ab]
        shares = [r["recompute_queue_share"] for r in ab if r["recompute_queue_share"] is not None]
        mx = max(shares) if shares else None
        L.append(f"  - {c} (baseline N={lim[c]['base_n']}): " + "; ".join(parts)
                 + f". Max {fmt(mx)} -> {'>= 10%' if mx is not None and mx >= KILL_SHARE else '< 10%'}{tag}")
    with open(os.path.join(out, "g3_summary.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
