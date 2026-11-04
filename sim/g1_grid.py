"""G1 grid: every policy x context x session count x pause mix x seed, then the oracle gap.

  python sim/g1_grid.py --out $DBKV_DATA/runs/g1/<id> [--procs 32] [--quick]

Writes results.csv (one row per run) and gap.csv (per mix/ctx/N: best per-tool policy vs best
oracle at p95, mean over seeds). Copies gap.csv to results/g1_gap.csv in the repo.
"""
import argparse, csv, os, shutil, sys, time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kvsim import Cfg, simulate  # noqa: E402

SESSIONS = {4096: [8, 16, 24, 32, 40, 48, 64, 96],
            8192: [4, 8, 12, 16, 20, 24, 32, 48],
            20480: [2, 4, 6, 8, 10, 12, 16, 20]}
LIMIT = {4096: 32.4, 8192: 16.2, 20480: 6.5}  # prediction 1a (mid)
TTLS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 30]
THS = TTLS  # same thresholds as the timeout sweep, so the two families are matched
# (policy, sched). "Per-tool" = anything that can't see the individual call's duration.
PER_TOOL = [("lru", "request"), ("lru", "program"), ("keep", "program"), ("cont2", "program"),
            ("contpaper", "program")] + [(f"ttl:{x}", "program") for x in TTLS]
ORACLE = [(f"oracle:{th}", "program") for th in THS]
NOISY = [(f"noisy:{s}:{th}", "program") for s in (0.5, 1.0) for th in (2, 5, 10)]


def run(args):
    kw = args
    t = time.time()
    r = simulate(Cfg(**kw))
    r["wall_s"] = round(time.time() - t, 2)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=os.cpu_count())
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--quick", action="store_true", help="short horizon, 1 seed (debug)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    seeds = 1 if a.quick else a.seeds
    extra = dict(warmup=60, horizon=360) if a.quick else {}
    jobs = []
    for mix in ("redshift", "ms"):
        for ctx, ns in SESSIONS.items():
            for n in ns:
                for pol, sched in PER_TOOL + ORACLE + NOISY:
                    for s in range(seeds):
                        jobs.append(dict(ctx=ctx, sessions=n, mix=mix, policy=pol, sched=sched, seed=s, **extra))
    t = time.time()
    with Pool(a.procs) as p:
        rows = p.map(run, jobs, chunksize=4)
    print(f"{len(rows)} runs in {time.time() - t:.0f} s on {a.procs} procs", flush=True)
    with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    # gap table: mean p95 over seeds per (mix, ctx, N, policy, sched)
    from collections import defaultdict
    agg = defaultdict(list)
    for r in rows:
        agg[(r["mix"], r["ctx"], r["sessions"], r["policy"], r["sched"])].append(r["task_p95"])
    mean = {k: float(np.nanmean(v)) for k, v in agg.items()}
    gap_rows = []
    for mix in ("redshift", "ms"):
        for ctx, ns in SESSIONS.items():
            for n in ns:
                def best(group):
                    c = [(mean[(mix, ctx, n, p, s)], p) for p, s in group if not np.isnan(mean[(mix, ctx, n, p, s)])]
                    return min(c) if c else (float("nan"), "-")
                bt, bt_pol = best(PER_TOOL)
                bo, bo_pol = best(ORACLE + [("keep", "program")])
                bn, bn_pol = best(NOISY)
                gap_rows.append(dict(
                    mix=mix, ctx=ctx, sessions=n, x_limit=round(n / LIMIT[ctx], 2),
                    stock_lru_p95=round(mean[(mix, ctx, n, "lru", "request")], 2),
                    cont2_p95=round(mean[(mix, ctx, n, "cont2", "program")], 2),
                    best_tool_p95=round(bt, 2), best_tool=bt_pol,
                    best_oracle_p95=round(bo, 2), best_oracle=bo_pol,
                    oracle_gap_pct=round(100 * (bt - bo) / bt, 1),
                    best_noisy_p95=round(bn, 2), best_noisy=bn_pol,
                    noisy_gap_pct=round(100 * (bt - bn) / bt, 1)))
    gp = os.path.join(a.out, "gap.csv")
    with open(gp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(gap_rows[0])); w.writeheader(); w.writerows(gap_rows)
    for g in gap_rows:
        print(g, flush=True)
    if not a.quick:
        repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
        os.makedirs(repo, exist_ok=True)
        shutil.copy(gp, os.path.join(repo, "g1_gap.csv"))


if __name__ == "__main__":
    main()
