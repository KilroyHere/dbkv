"""G1 grid (v2): policy x offload x context x sessions x pause mix/scale x seed, then the oracle gap.

  python sim/g1_grid.py --out $DBKV_DATA/runs/g1/<id> [--procs 32] [--quick]
        [--cost-json costs.json]           # G3-refitted t0/c_pf/c_dec/c_att/kv_tokens
        [--pause-file sf100_times.txt]     # adds an empirical mix (e.g. TPC-H SF100 query times)

Writes, in --out:
  results.csv   one row per run
  gap.csv       per (mix, scale, ctx, N): best per-tool policy vs best policy overall at p95,
                ratio = mean pause / mean generation time per turn, released-Continuum and keep lines
  breaker.csv   per (mix, scale, ctx, N, policy, offload): share of runs that hit the deadlock
                breaker, mean events and evicted tokens
  gap_vs_ratio.png
Copies gap.csv and breaker.csv to results/g1v2_*.csv in the repo (not with --quick).
"""
import argparse, csv, json, os, shutil, sys, time
from collections import defaultdict
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kvsim import Cfg, simulate  # noqa: E402

SESSIONS = {4096: [8, 16, 24, 32, 40, 48, 64, 96],
            8192: [4, 8, 12, 16, 20, 24, 32, 48],
            20480: [2, 4, 6, 8, 10, 12, 16, 20]}
LIMIT = {4096: 32.4, 8192: 16.2, 20480: 6.5}  # prediction 1a (mid)
TTLS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 30]
# Per-tool = can't see the individual call's duration. "Any" adds the per-call (oracle) family.
PER_TOOL = [("lru", "request"), ("lru", "program"), ("keep", "program"), ("keep-ac", "program"),
            ("cont2", "program"), ("contpaper", "program")] + [(f"ttl:{x}", "program") for x in TTLS]
ORACLE = [(f"oracle:{th}", "program") for th in TTLS]
NOISY = [(f"noisy:{s}:{th}", "program") for s in (0.5, 1.0) for th in (2, 5, 10)]
MIXES = [("redshift", 1.0), ("redshift", 3.0), ("redshift", 10.0), ("redshift", 30.0), ("ms", 1.0)]


def run(kw):
    t = time.time()
    r = simulate(Cfg(**kw))
    r["wall_s"] = round(time.time() - t, 2)
    r["mix"] = kw.get("mix", "redshift") if not kw.get("pause_file") else "file"
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=os.cpu_count())
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--quick", action="store_true", help="short horizon, 1 seed, fewer cells (debug)")
    ap.add_argument("--cost-json", default="", help="override Cfg cost fields (t0, c_pf, c_dec, c_att, kv_tokens)")
    ap.add_argument("--pause-file", default="", help="empirical pause seconds, added as mix 'file'")
    ap.add_argument("--from-results", default="", help="re-aggregate an existing results.csv instead of simulating")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    costs = json.load(open(a.cost_json)) if a.cost_json else {}
    seeds = 1 if a.quick else a.seeds
    mixes = list(MIXES) + ([("file", 1.0)] if a.pause_file else [])
    jobs = []
    for mix, scale in mixes:
        # long pauses need a longer window for enough completed tasks
        meas = 1200.0 * max(1.0, scale / 3.0)
        extra = dict(warmup=60.0, horizon=60.0 + 300.0 * max(1.0, scale / 3.0)) if a.quick else \
            dict(warmup=120.0, horizon=120.0 + meas)
        for ctx, ns in SESSIONS.items():
            for n in (ns[::2] if a.quick else ns):
                for pol, sched in PER_TOOL + ORACLE + NOISY:
                    for off in (False, True):
                        if pol == "lru" and sched == "request" and off:
                            continue  # stock vLLM has no offload here
                        for s in range(seeds):
                            kw = dict(ctx=ctx, sessions=n, policy=pol, sched=sched, offload=off,
                                      pause_scale=scale, seed=s, **extra, **costs)
                            if mix == "file":
                                kw["pause_file"] = a.pause_file
                            else:
                                kw["mix"] = mix
                            jobs.append(kw)
    if a.from_results:
        rows = []
        for r in csv.DictReader(open(a.from_results)):
            for k, v in r.items():
                if k not in ("mix", "policy", "sched"):
                    r[k] = float(v) if ("." in v or "e" in v or v == "nan") else int(v)
            rows.append(r)
        print(f"re-aggregating {len(rows)} runs from {a.from_results}", flush=True)
    else:
        print(f"{len(jobs)} runs on {a.procs} procs", flush=True)
        t = time.time()
        with Pool(a.procs) as p:
            rows = p.map(run, jobs, chunksize=8)
        print(f"done in {time.time() - t:.0f} s", flush=True)
        with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    json.dump(dict(costs=costs, seeds=seeds, quick=a.quick, pause_file=a.pause_file, mixes=mixes),
              open(os.path.join(a.out, "config.json"), "w"), indent=1)

    # --- aggregate over seeds ---
    agg = defaultdict(list)
    for r in rows:
        agg[(r["mix"], r["pause_scale"], r["ctx"], r["sessions"], r["policy"], r["sched"], r["offload"])].append(r)

    def m(key, field):
        # Strict: if any seed completed no measured task (p95 = NaN, i.e. agents starved), the
        # policy is invalid at this cell (NaN), never averaged over the surviving seeds.
        v = [x[field] for x in agg.get(key, [])]
        if not v or any(x != x for x in v):
            return float("nan")
        return float(np.mean(v))

    def starved(key):
        return sum(x["task_p95"] != x["task_p95"] for x in agg.get(key, []))

    gap_rows, brk_rows = [], []
    for mix, scale in mixes:
        for ctx, ns in SESSIONS.items():
            for n in (ns[::2] if a.quick else ns):
                cell = (mix, scale, ctx, n)

                # Throughput validity: p95 is over *completed* tasks, so a policy that finishes few tasks
                # (only the fast ones) looks deceptively good. A policy counts at this cell only if its mean
                # completed-task count is >= 50% of the best policy's at the cell.
                tmax = max((m(k, "tasks") for k in agg if k[:4] == cell), default=0.0)

                def valid(key):
                    t = m(key, "tasks")
                    return t == t and t >= 0.5 * tmax

                def best(group, offs=(0, 1)):
                    c = [(m(cell + (p, s, o), "task_p95"), f"{p}{'+off' if o else ''}")
                         for p, s in group for o in offs if (cell + (p, s, o)) in agg and valid(cell + (p, s, o))]
                    c = [x for x in c if x[0] == x[0]]
                    return min(c) if c else (float("nan"), "-")
                bt, bt_pol = best(PER_TOOL)
                ba, ba_pol = best(PER_TOOL + ORACLE)
                bn, bn_pol = best(PER_TOOL + NOISY)
                cell_rows = [r for k, v in agg.items() if k[:4] == cell for r in v]
                gen = np.nanmean([r["gen_mean"] for r in cell_rows])
                pause = np.nanmean([r["pause_mean"] for r in cell_rows])
                cont2 = m(cell + ("cont2", "program", 0), "task_p95")
                keep = m(cell + ("keep", "program", 0), "task_p95")
                keepac = m(cell + ("keep-ac", "program", 0), "task_p95")
                stock = m(cell + ("lru", "request", 0), "task_p95")
                gap_rows.append(dict(
                    mix=mix, pause_scale=scale, ctx=ctx, sessions=n, x_limit=round(n / LIMIT[ctx], 2),
                    pause_mean=round(pause, 3), gen_mean=round(gen, 3), ratio=round(pause / gen, 3),
                    stock_p95=round(stock, 2), cont2_p95=round(cont2, 2),
                    keep_breaker_p95=round(keep, 2), keep_ac_p95=round(keepac, 2),
                    cont2_vs_keep_ac_pct=round(100 * (cont2 - keepac) / keepac, 1),
                    best_tool_p95=round(bt, 2), best_tool=bt_pol,
                    best_any_p95=round(ba, 2), best_any=ba_pol,
                    oracle_gap_pct=round(100 * (bt - ba) / bt, 1),
                    best_noisy_p95=round(bn, 2), best_noisy=bn_pol,
                    noisy_gap_pct=round(100 * (bt - bn) / bt, 1)))
                for p, s in PER_TOOL + ORACLE + NOISY:
                    for o in (0, 1):
                        rs = agg.get(cell + (p, s, o))
                        if not rs:
                            continue
                        brk_rows.append(dict(
                            mix=mix, pause_scale=scale, ctx=ctx, sessions=n, policy=p, sched=s, offload=o,
                            runs=len(rs), runs_with_breaker=sum(r["breaker_events"] > 0 for r in rs),
                            breaker_events_mean=round(float(np.mean([r["breaker_events"] for r in rs])), 1),
                            breaker_tokens_mean=int(np.mean([r["breaker_tokens"] for r in rs])),
                            seeds_starved=starved(cell + (p, s, o)),
                            tasks_mean=round(m(cell + (p, s, o), "tasks"), 1),
                            task_p95=round(m(cell + (p, s, o), "task_p95"), 2)))

    for name, rows_ in (("gap.csv", gap_rows), ("breaker.csv", brk_rows)):
        with open(os.path.join(a.out, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_[0])); w.writeheader(); w.writerows(rows_)

    tot = defaultdict(lambda: [0, 0])
    for b in brk_rows:
        k = b["policy"] + ("+off" if b["offload"] else "")
        tot[k][0] += b["runs_with_breaker"]; tot[k][1] += b["runs"]
    print("share of runs hitting the deadlock breaker, per policy:")
    for k, (h, n) in sorted(tot.items(), key=lambda x: -x[1][0] / x[1][1]):
        print(f"  {k:22s} {100 * h / n:5.1f}%  ({h}/{n})")

    plot(gap_rows, os.path.join(a.out, "gap_vs_ratio.png"))
    if not a.quick:
        repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
        os.makedirs(repo, exist_ok=True)
        shutil.copy(os.path.join(a.out, "gap.csv"), os.path.join(repo, "g1v2_gap.csv"))
        shutil.copy(os.path.join(a.out, "breaker.csv"), os.path.join(repo, "g1v2_breaker.csv"))
        shutil.copy(os.path.join(a.out, "gap_vs_ratio.png"), os.path.join(repo, "g1v2_gap_vs_ratio.png"))


def plot(gap_rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {4096: "#2a78d6", 8192: "#1baf7a", 20480: "#eb6834"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, (lo, hi, title) in zip(axes, [(0, 1.0, "below the limit (≤1×)"), (1.2, 99, "above the limit (≥1.2×)")]):
        for ctx, c in colors.items():
            pts = [(g["ratio"], g["oracle_gap_pct"]) for g in gap_rows
                   if g["ctx"] == ctx and lo <= g["x_limit"] <= hi and g["mix"] != "ms" and g["ratio"] == g["ratio"]]
            if pts:
                x, y = zip(*sorted(pts))
                ax.scatter(x, y, s=18, color=c, label=f"{ctx // 1024}k context")
        ax.axhline(10, color="#888", lw=1, ls="--")
        ax.text(0.02, 10.5, "G1 kill line (10%)", color="#666", fontsize=8,
                transform=ax.get_yaxis_transform())
        ax.set_xscale("log"); ax.set_title(title, fontsize=10)
        ax.set_xlabel("mean pause ÷ mean generation time per turn")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("oracle gap at p95 (%)")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("Where knowing query durations starts to matter (G1 v2)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


if __name__ == "__main__":
    main()
