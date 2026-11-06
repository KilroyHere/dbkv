"""Open-loop capacity + per-policy predictions for Phase 2 (PLAN 2f), using sim/openloop.py.

  python sim/openloop_rates.py --out $SCRATCH/dbkv/runs/openloop [--procs 32]

Two engine-cost variants, both reported:
  g3   g3_costs.json as measured (the instructed model)
  cal  c_dec and c_att x CAL (fit so the closed-loop sim matches step 6's real explore cells at c = 8/32/64;
       see summary.md). Everything else identical.
Steps: (1) K from the time-averaged context of an active task at low load; (2) stock capacity sweep over
lambda (30-min windows) + closed-loop throughput vs N; (3) rates 0.6/1.0/1.3 x capacity; (4) policies x
rates x 5 seeds, 8-min window (and a 30-min stability window). Writes summary.md / summary.json / runs.jsonl.
"""
import argparse, json, math, os, sys, time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openloop import cfg_from_costs, load_traces, simulate, load_costs  # noqa: E402

CAL = 2.0
SEEDS = [0, 1, 2, 3, 4]
REAL_CLOSED = {8: (4.47, 12.55), 32: (9.18, 25.36), 64: (16.88, 45.80)}  # step 6 explore, caching on
TR = None


def model_kw(model):
    if model == "g3":
        return {}
    c = load_costs()
    return dict(c_dec=c["c_dec"] * CAL, c_att=c["c_att"] * CAL)


def run(job):
    global TR
    if TR is None:
        TR = load_traces()
    model, kw, tag = job
    t = time.time()
    r = simulate(cfg_from_costs(**model_kw(model), **kw), TR)
    r.update(model=model, tag=tag, wall=round(time.time() - t, 1))
    return r


def ms(xs):
    xs = [x for x in xs if x == x]
    if not xs:
        return float("nan"), float("nan")
    return float(np.mean(xs)), float(np.std(xs, ddof=1)) if len(xs) > 1 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expandvars("$SCRATCH/dbkv/runs/openloop"))
    ap.add_argument("--procs", type=int, default=32)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pool = Pool(a.procs)
    models = ["g3", "cal"]
    allruns = []
    S = dict(models={"g3": load_costs(), "cal": {**load_costs(), **model_kw("cal")}}, cal_factor=CAL)

    # (0) closed-loop fidelity vs step 6 + closed-loop throughput vs N
    Ns = [8, 16, 32, 48, 64, 80, 96, 112, 128, 160]
    jobs = [(m, dict(closed=n, measure=1200, drain=0, seed=s), f"closed{n}") for m in models for n in Ns
            for s in SEEDS[:3]]
    res = pool.map(run, jobs); allruns += res
    S["closed"] = {m: {n: dict(zip(("p50", "p50_sd"), ms([r["p50"] for r in res if r["model"] == m and r["closed"] == n])))
                       | dict(zip(("p95", "p95_sd"), ms([r["p95"] for r in res if r["model"] == m and r["closed"] == n])))
                       | dict(thr=ms([r["thr"] for r in res if r["model"] == m and r["closed"] == n])[0],
                              preempt=ms([r["preempt"] for r in res if r["model"] == m and r["closed"] == n])[0])
                       for n in Ns} for m in models}
    print("closed done", flush=True)

    # (1) K: time-averaged context (incl. the shared prefix) of an active task, stock, low load
    jobs = [(m, dict(lam=60, measure=1800, drain=300, seed=s, track_ctx=True), "ctx") for m in models for s in SEEDS]
    res = pool.map(run, jobs); allruns += res
    M = load_costs()["kv_tokens"]
    S["K"] = {}
    for m in models:
        c = float(np.mean([r["ctx_per_active"] for r in res if r["model"] == m]))
        S["K"][m] = dict(ctx_per_active=c, K=int(M // c), K_ctx_minus25=int(M // (0.75 * c)),
                         K_ctx_plus25=int(M // (1.25 * c)),
                         mean_active_at_60=float(np.mean([r["mean_active"] for r in res if r["model"] == m])))
    print("K", S["K"], flush=True)

    # (2) stock capacity sweep, 30-min windows
    lams = list(range(60, 421, 20))
    jobs = [(m, dict(lam=l, measure=1800, drain=600, seed=s), "cap") for m in models for l in lams for s in SEEDS[:3]]
    res = pool.map(run, jobs); allruns += res
    S["capacity"] = {}
    for m in models:
        rows = []
        for l in lams:
            rr = [r for r in res if r["model"] == m and r["lam"] == l]
            rows.append(dict(lam=l, compl_ratio=ms([r["compl_ratio"] for r in rr])[0],
                             thr=ms([r["thr"] for r in rr])[0], p50=ms([r["p50"] for r in rr])[0],
                             p95=ms([r["p95"] for r in rr])[0],
                             active_growth=ms([r["active_end"] - r["active_start"] for r in rr])[0],
                             preempt=ms([r["preempt"] for r in rr])[0]))
        sat = next((x["lam"] for x in rows if x["compl_ratio"] < 0.95 or x["active_growth"] > 50), float("nan"))
        last_ok = max((x["lam"] for x in rows if x["lam"] < sat), default=float("nan"))
        S["capacity"][m] = dict(rows=rows, first_saturated=sat, last_stable=last_ok,
                                capacity=(sat + last_ok) / 2, max_thr=max(x["thr"] for x in rows))
    print("cap", {m: (S["capacity"][m]["last_stable"], S["capacity"][m]["first_saturated"]) for m in models}, flush=True)

    # (3) rates (per model), rounded to 10 tasks/min
    S["rates"] = {m: {name: int(round(f * S["capacity"][m]["capacity"] / 10.0) * 10)
                      for name, f in (("below", 0.6), ("at", 1.0), ("above", 1.3))} for m in models}

    # (4) policies x rates x seeds
    jobs = []
    for m in models:
        K = S["K"][m]["K"]
        pols = [("stock", 0), ("priority", 0), ("admission", K), ("both", K),
                ("admission", int(round(0.75 * K))), ("admission", int(round(1.25 * K))),
                ("both", int(round(0.75 * K))), ("both", int(round(1.25 * K)))]
        for name, lam in S["rates"][m].items():
            for pol, k in pols:
                for s in SEEDS:
                    jobs.append((m, dict(lam=lam, policy=pol, K=k, measure=480, drain=900, seed=s), f"w8:{name}"))
                    if (pol, k) in (("stock", 0), ("priority", 0), ("admission", K), ("both", K)):
                        jobs.append((m, dict(lam=lam, policy=pol, K=k, measure=1800, drain=1800, seed=s),
                                     f"w30:{name}"))
    res = pool.map(run, jobs); allruns += res
    keys = ["p50", "p95", "thr", "preempt", "wait_mean", "wait_p95", "idle_frac", "unfinished", "arrived",
            "p50_done_in_win", "p95_done_in_win", "mean_running"]
    S["grid"] = []
    for m in models:
        for tag in sorted({r["tag"] for r in res}):
            for pol, k in sorted({(r["policy"], r["K"]) for r in res if r["model"] == m and r["tag"] == tag}):
                rr = [r for r in res if r["model"] == m and r["tag"] == tag and r["policy"] == pol and r["K"] == k]
                row = dict(model=m, window=tag.split(":")[0], rate=tag.split(":")[1], lam=rr[0]["lam"],
                           policy=pol, K=k, n=len(rr))
                for kk in keys:
                    mu, sd = ms([r[kk] for r in rr]); row[kk] = mu; row[kk + "_sd"] = sd
                S["grid"].append(row)

    with open(os.path.join(a.out, "runs.jsonl"), "w") as f:
        for r in allruns:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(S, f, indent=1, default=float)
    write_md(S, os.path.join(a.out, "summary.md"))
    print("done", flush=True)


def write_md(S, path):
    L = ["# Open-loop simulator: capacity and Phase 2 predictions (sim/openloop.py)", ""]
    L.append("Workload: tasks resampled from the explore arm, all 1,534 BIRD dev questions (job 60873599), "
             "token counts + tool times only. Engine: kvsim iteration model, pool 139,232 tokens, budget 2048, "
             "max 256 seqs, shared 464-token system prompt resident once. Models: **g3** = g3_costs.json; "
             f"**cal** = c_dec, c_att x {S['cal_factor']} (fit to step-6 closed-loop cells).")
    L += ["", "## Closed-loop fidelity (sim vs step 6 explore, caching on; p50/p95 s)", "",
          "| N | real | g3 sim | cal sim | g3 thr/min | cal thr/min |", "|---|---|---|---|---|---|"]
    for n, c in S["closed"]["g3"].items():
        rc = REAL_CLOSED.get(n)
        cc = S["closed"]["cal"][n]
        L.append(f"| {n} | {('%.2f / %.2f' % rc) if rc else '-'} | {c['p50']:.2f} / {c['p95']:.2f} | "
                 f"{cc['p50']:.2f} / {cc['p95']:.2f} | {c['thr']:.0f} | {cc['thr']:.0f} |")
    L += ["", "## K", ""]
    for m, k in S["K"].items():
        L.append(f"- {m}: time-averaged context per active task = {k['ctx_per_active']:.0f} tokens "
                 f"(incl. 464 shared) -> K = floor(139232 / {k['ctx_per_active']:.0f}) = **{k['K']}**; "
                 f"context -25% -> K = {k['K_ctx_minus25']}, +25% -> K = {k['K_ctx_plus25']}. "
                 "Grid also runs K x 0.75 and K x 1.25.")
    L += ["", "## Stock capacity sweep (30-min window, 3 seeds)", ""]
    for m, c in S["capacity"].items():
        L += [f"**{m}**: last stable {c['last_stable']}/min, first saturated {c['first_saturated']}/min, "
              f"capacity ~{c['capacity']:.0f}/min, max throughput {c['max_thr']:.0f}/min. "
              f"Rates: {S['rates'][m]}", "",
              "| lambda | completed/arrived | thr/min | p50 | p95 | active growth | preempt |",
              "|---|---|---|---|---|---|---|"]
        for x in c["rows"]:
            L.append(f"| {x['lam']} | {x['compl_ratio']:.3f} | {x['thr']:.0f} | {x['p50']:.1f} | {x['p95']:.1f} | "
                     f"{x['active_growth']:.0f} | {x['preempt']:.0f} |")
        L.append("")
    for w in ("w8", "w30"):
        L += [f"## Policies, {'8-min' if w == 'w8' else '30-min'} window (mean ± sd over 5 seeds)", "",
              "| model | rate | lambda | policy | K | p50 s | p95 s | thr/min | preempt | queue wait mean s | idle | unfinished |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        order = {"below": 0, "at": 1, "above": 2}
        for r in sorted((r for r in S["grid"] if r["window"] == w),
                        key=lambda r: (r["model"], order[r["rate"]], r["policy"], r["K"])):
            L.append(f"| {r['model']} | {r['rate']} | {r['lam']} | {r['policy']} | {r['K'] or '-'} | "
                     f"{r['p50']:.1f} ± {r['p50_sd']:.1f} | {r['p95']:.1f} ± {r['p95_sd']:.1f} | "
                     f"{r['thr']:.0f} ± {r['thr_sd']:.0f} | {r['preempt']:.0f} | {r['wait_mean']:.1f} | "
                     f"{r['idle_frac']:.3f} | {r['unfinished']:.0f} |")
        L.append("")
    L += ["## Caveats", "",
          "- g1_fidelity.csv: sim within ±14% of real vLLM above the KV limit but underestimates resume latency below it.",
          "- Trace recorded at concurrency 8: only token counts and tool times are used; per-turn off-GPU overhead fixed at 15 ms (c = 8 median; real grows to ~60 ms at c = 64).",
          "- The g3 model is ~25% optimistic at c = 64 in closed loop (iteration time 52 vs 69 ms real); cal fixes that by fiat (one factor, three points).",
          "- p50/p95 are over tasks arriving in the window; tasks unfinished at the end of the drain count with their elapsed time (lower bound).",
          "- Preemption = full recompute; vLLM may get some prefix hits back. Admission order inside vLLM stops at the first request that can't fit."]
    open(path, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
