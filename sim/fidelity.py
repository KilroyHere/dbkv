"""Tier-2 item 1: simulator fidelity against G3. Re-run the G3 cells in the simulator, with stock
vLLM policy (LRU, request FCFS), the G3 workload settings and the G3-refitted costs, then compare p95s.

  python sim/fidelity.py $SCRATCH/dbkv/runs/g3/main --costs results/g3_costs.json --out results/g1_fidelity.csv

Per cell: measured mean over reps vs simulated mean over seeds for task p95 and resume-TTFT p95,
with the relative error (sim - meas) / meas.
"""
import argparse, csv, glob, json, os, sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kvsim import Cfg, simulate  # noqa: E402


def sim(kw):
    return simulate(Cfg(**kw))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--costs", required=True)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    costs = json.load(open(a.costs))
    meas = {}
    for sp in glob.glob(os.path.join(a.run, "rep*", "c*_n*_r0", "summary.json")):
        d = json.load(open(sp))
        meas.setdefault((d["ctx"], d["sessions"]), []).append(d)
    jobs = []
    for (ctx, n), ds in meas.items():
        d = ds[0]
        for s in range(a.seeds):
            jobs.append(dict(ctx=ctx, sessions=n, policy="lru", sched="request", offload=False,
                             turns=d["turns"], warmup=d["warmup"], horizon=d["warmup"] + d["duration"],
                             mix=d.get("mix", "redshift"), seed=s, **costs))
    with Pool(a.procs) as p:
        res = p.map(sim, jobs)
    simd = {}
    for r in res:
        simd.setdefault((r["ctx"], r["sessions"]), []).append(r)

    def mean(xs):
        xs = [x for x in xs if x is not None and x == x]
        return float(np.mean(xs)) if xs else float("nan")
    rows = []
    for key in sorted(meas):
        m, s = meas[key], simd.get(key, [])
        mt, st = mean([d["task_p95"] for d in m]), mean([r["task_p95"] for r in s])
        mr, sr = mean([d["resume_ttft_p95"] for d in m]), mean([r["resume_p95"] for r in s])
        rows.append(dict(ctx=key[0], sessions=key[1], reps=len(m),
                         meas_task_p95=round(mt, 2), sim_task_p95=round(st, 2),
                         task_err_pct=round(100 * (st - mt) / mt, 1) if mt == mt and st == st else float("nan"),
                         meas_resume_p95=round(mr, 3), sim_resume_p95=round(sr, 3),
                         resume_err_pct=round(100 * (sr - mr) / mr, 1) if mr == mr and sr == sr else float("nan"),
                         meas_tasks=round(mean([d["tasks"] for d in m]), 1), sim_tasks=round(mean([r["tasks"] for r in s]), 1)))
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(r)
    e = [abs(r["task_err_pct"]) for r in rows if r["task_err_pct"] == r["task_err_pct"]]
    print(f"task p95 |error|: median {np.median(e):.1f}%, max {max(e):.1f}%, cells within 25%: {sum(x <= 25 for x in e)}/{len(e)}")


if __name__ == "__main__":
    main()
