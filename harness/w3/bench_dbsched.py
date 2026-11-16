"""CPU replay benchmark for option D (harness/w3/dbsched.py): recorded agent SQL from the Phase 1 traces, replayed
against the real DuckDB files through the same asyncio.to_thread(tools.call, ...) path as the frozen agent.

    B=harness/w3/bench_dbsched.py
    python $B extract --runs /pscratch/sd/a/ap2568/dbkv/runs/p1 --out $W/trace.json        # login node OK (JSON only)
    python $B calib   --trace $W/trace.json --out $W/calib.csv --procs 3 --budget-s 660    # compute node
    python $B fit     --calib $W/calib.csv --g2 $DBKV_DATA/runs/g2/60826277/results.csv \
                      --model-out harness/w3/dbsched_model.json --report $W/calib_report.json
    python $B run     --trace $W/trace.json --db tpch_sf100 --agents 32 --arms off,explain,off \
                      --arm-s 390 --warm-s 60 --out $W/run1                                  # compute node

extract: one record per traced task (tenant, db path, template, per turn: the LLM time `client_s` and the turn's
  tool calls rebuilt as (name, args)). Only cells at light load (closed:1, closed:4, open:20/30/40) by default, so
  the LLM gaps are close to what an unloaded GPU gives.
calib: each unique execute_sql text once, alone (--procs separate processes = separate DuckDB instances, the
  agent's settings: threads 8, memory_limit 16GB), EXPLAIN features + runtime (timeout --timeout, censored as
  long). Random order, stops starting new queries after --budget-s.
fit: 3-class accuracy (short < 0.25 s <= medium < 2 s <= long) of the EXPLAIN model on agent SQL:
  (a) trained on G2's SF100 queries only (no agent data), (b) leave-one-template-out on agent SQL,
  (c) the final model (G2 + agent SQL) written to --model-out for dbsched.
run: arms in sequence in one process (e.g. off,explain,off = A-B-A). Each arm: a fresh executor
  (dbsched.make_executor) as the loop's default executor, --agents closed-loop agents (or --rate open-loop
  arrivals per minute), each replaying tasks from the trace in the same fixed order in every arm: sleep the turn's
  LLM time, then run its tool calls one by one via asyncio.to_thread(tools.call, ...). Tasks that start in
  [warm-s, arm-s) are measured; after arm-s no new task starts; unfinished tasks are cut at --drain-s and counted
  at their elapsed time. Writes per arm tasks_<k>_<arm>.jsonl, calls_<k>_<arm>.jsonl, dbsched_<k>_<arm>.jsonl,
  and summary.json.
"""
import argparse, asyncio, collections, csv, glob, hashlib, json, os, random, re, sys, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "calib"))
sys.path.insert(0, os.path.join(REPO, "harness", "agent_duckdb"))

LIGHT = ("01_closed_1_30", "01_closed_4_60", "01_open_20", "01_open_30", "01_open_40")
SHORT_S, LONG_S = 0.25, 2.0
CLS = ["short", "medium", "long"]

_DESC = re.compile(r"lower\(table_name\) = lower\('((?:[^']|'')*)'\)")
_SAMPLE = re.compile(r'^SELECT \* FROM "((?:[^"]|"")*)" LIMIT (\d+)$')


def tool_args(t):
    """Rebuild (name, args) of a recorded tool call from its name and SQL."""
    name, sql = t["name"], t.get("sql") or ""
    if name == "describe_table":
        m = _DESC.search(sql)
        return name, {"table": m.group(1).replace("''", "'") if m else ""}
    if name == "sample_rows":
        m = _SAMPLE.match(sql)
        return name, ({"table": m.group(1).replace('""', '"'), "n": int(m.group(2))} if m else {"table": ""})
    if name == "execute_sql":
        return name, {"sql": sql}
    return name, {}


def cls_of(sec):
    return "short" if sec < SHORT_S else ("medium" if sec < LONG_S else "long")


# ---------------------------------------------------------------------------------------------------- extract
def cmd_extract(a):
    paths = {}
    for f in glob.glob(os.path.join(os.environ.get("DBKV_DATA", "/pscratch/sd/a/ap2568/dbkv"), "w3/streams/*.jsonl")):
        for l in open(f):
            t = json.loads(l)
            paths[t["tenant"]] = t["db_path"]
        if len(paths) >= 3:
            break
    cells = a.cells.split(",") if a.cells else LIGHT
    out = []
    for job in sorted(os.listdir(a.runs)):
        for cell in cells:
            d = os.path.join(a.runs, job, cell)
            if not os.path.exists(os.path.join(d, "turns.jsonl")):
                continue
            tmpl = {}
            for l in open(os.path.join(d, "tasks.jsonl")):
                r = json.loads(l)
                tmpl[r.get("task_id") or r["qid"]] = r.get("template_id")
            by = collections.OrderedDict()
            for l in open(os.path.join(d, "turns.jsonl")):
                r = json.loads(l)
                by.setdefault(r.get("task_id") or r["qid"], []).append(r)
            for k, turns in by.items():
                turns.sort(key=lambda r: r["turn"])
                db = turns[0]["db"]
                out.append(dict(key=f"{job}/{cell}/{k}", qid=turns[0]["qid"], tenant=db, db_path=paths[db],
                                template_id=tmpl.get(k),
                                turns=[dict(llm_s=r["client_s"], tools=[list(tool_args(t)) + [t.get("runtime_s"),
                                                                                              t.get("error")]
                                                                       for t in r.get("tools") or []])
                                       for r in turns]))
    random.Random(0).shuffle(out)  # fixed task order for every arm
    json.dump(out, open(a.out, "w"))
    c = collections.Counter(t["tenant"] for t in out)
    print(f"{len(out)} tasks from cells {cells}: {dict(c)} -> {a.out}")


# ---------------------------------------------------------------------------------------------------- calib
def _calib_worker(args):
    import duckdb, g2_run, tools_duckdb as tools
    rows, budget_end, timeout, wid = args
    out = []
    br = {}
    for r in rows:
        if time.time() > budget_end:
            break
        rec = dict(r)
        try:
            con = tools.connect(r["db_path"])
        except Exception as e:  # noqa: BLE001
            rec.update(status="connect_error", error=str(e)[:200]); out.append(rec); continue
        try:
            if r["db_path"] not in br:
                br[r["db_path"]] = dict(con.execute("select table_name, estimated_size from duckdb_tables()").fetchall())
            ms, roots = g2_run.explain(con, r["sql"])
            ms2, _ = g2_run.explain(con, r["sql"])
            rec.update(explain_ms=round(ms, 3), explain_ms2=round(ms2, 3))
            rec.update(g2_run.plan_features(roots, br[r["db_path"]]))
        except Exception as e:  # noqa: BLE001
            rec.update(status="explain_error", error=f"{type(e).__name__}: {str(e)[:160]}")
            con.close(); out.append(rec); continue
        con.close()
        cols, res, rt, err, msg = tools.run_query(r["db_path"], r["sql"], timeout=timeout, max_rows=tools.MAX_ROWS)
        if err == "timeout":
            rec.update(status="timeout", runtime_s=timeout, censored=1)
        elif err:
            rec.update(status="query_error", runtime_s=rt, error=err)
        else:
            rec.update(status="ok", runtime_s=rt, censored=0)
        out.append(rec)
        print(f"[w{wid}] {len(out)}/{len(rows)} {r['tenant']} {rec['status']} {rec.get('runtime_s')}", flush=True)
    return out


def cmd_calib(a):
    from multiprocessing import Pool
    trace = json.load(open(a.trace))
    seen, rows = set(), []
    quota = dict(kv.split("=") for kv in a.quota.split(","))
    for t in trace:
        for turn in t["turns"]:
            for name, args, rt, err in turn["tools"]:
                if name != "execute_sql":
                    continue
                k = (t["tenant"], args["sql"])
                if k in seen:
                    continue
                seen.add(k)
                rows.append(dict(tenant=t["tenant"], db_path=t["db_path"], template_id=t["template_id"],
                                 sql=args["sql"], sql_id=hashlib.sha1(args["sql"].encode()).hexdigest()[:12],
                                 trace_runtime_s=rt, trace_error=err))
    random.Random(1).shuffle(rows)
    pick, n = [], collections.Counter()
    for r in rows:
        if n[r["tenant"]] < int(quota.get(r["tenant"], 0)):
            pick.append(r); n[r["tenant"]] += 1
    print(f"{len(rows)} unique agent SQL; calibrating {dict(n)} with {a.procs} procs, timeout {a.timeout}s", flush=True)
    end = time.time() + a.budget_s
    shards = [pick[i::a.procs] for i in range(a.procs)]
    with Pool(a.procs) as p:
        res = p.map(_calib_worker, [(s, end, a.timeout, i) for i, s in enumerate(shards)])
    allr = [r for s in res for r in s]
    keys = sorted({k for r in allr for k in r})
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(allr)
    print(f"{len(allr)} rows -> {a.out}: {collections.Counter((r['tenant'], r['status']) for r in allr)}")


# ---------------------------------------------------------------------------------------------------- fit
def cmd_fit(a):
    import pandas as pd
    from scipy.stats import spearmanr
    import g2_analyze as G
    d = pd.read_csv(a.calib)
    d = d[d["status"].isin(["ok", "timeout"])].copy()
    d["y"] = d["runtime_s"].astype(float).clip(lower=1e-4)
    d["template"] = d["tenant"] + ":" + d["template_id"].astype(str)
    g2 = pd.read_csv(a.g2)
    g2 = g2[g2["status"].isin(["ok", "timeout"])].copy()
    g2["y"] = g2["median_s"].astype(float).clip(lower=1e-4)

    def acc(y, plog, tag):
        t = G.to_cls(y, SHORT_S, LONG_S)
        p = G.to_cls(10 ** plog, SHORT_S, LONG_S)
        cm = np.zeros((3, 3), int)
        for i, j in zip(t, p):
            cm[i, j] += 1
        return dict(subset=tag, n=int(len(y)), acc=round(float((t == p).mean()), 3),
                    rho=round(float(spearmanr(plog, y).statistic), 3), confusion=cm.tolist(),
                    long_recall=round(float(cm[2, 2] / max(1, cm[2].sum())), 3),
                    long_precision=round(float(cm[2, 2] / max(1, cm[:, 2].sum())), 3),
                    true_counts=cm.sum(1).tolist())

    rep = dict(n_agent=int(len(d)), by_tenant=d["tenant"].value_counts().to_dict(), results=[])
    X2, y2 = G.design(g2), np.log10(g2["y"].values)
    Xa, ya = G.design(d), np.log10(d["y"].values)
    f_g2 = G.huber_fit(X2, y2)
    pa = f_g2(Xa)
    for ten in [None] + sorted(d["tenant"].unique()):
        m = np.ones(len(d), bool) if ten is None else (d["tenant"] == ten).values
        rep["results"].append(dict(acc(d["y"].values[m], pa[m], ten or "all"), model="g2_sf100_only"))
    # LOTO on agent SQL (+ all of G2 in training)
    pl = np.full(len(d), np.nan)
    for tp in d["template"].unique():
        te = (d["template"] == tp).values
        f = G.huber_fit(np.vstack([X2, Xa[~te]]), np.concatenate([y2, ya[~te]]))
        pl[te] = f(Xa[te])
    for ten in [None] + sorted(d["tenant"].unique()):
        m = np.ones(len(d), bool) if ten is None else (d["tenant"] == ten).values
        rep["results"].append(dict(acc(d["y"].values[m], pl[m], ten or "all"), model="g2+agent_loto"))
    # single feature baseline: sum_ec thresholds fit on G2
    s = np.log10(d["sum_ec"].astype(float).values + 1)
    rep["sum_ec_rho"] = round(float(spearmanr(s, d["y"]).statistic), 3)
    # final model (G2 + all agent SQL) in dbsched's JSON format
    X, y = np.vstack([X2, Xa]), np.concatenate([y2, ya])
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    w = np.ones(len(y))
    P = 1e-2 * np.eye(Z.shape[1]); P[0, 0] = 0
    b = np.zeros(Z.shape[1])
    for _ in range(50):  # same IRLS as calib/g2_analyze.huber_fit, kept here to export the coefficients
        W = Z * w[:, None]
        b = np.linalg.solve(Z.T @ W + P * len(y), W.T @ y)
        r = y - Z @ b
        sc = np.median(np.abs(r)) / 0.6745 + 1e-9
        aa = np.abs(r) / sc
        w = np.where(aa <= 1, 1.0, 1.0 / np.maximum(aa, 1e-12))
    pf = Z[len(X2):] @ b
    rep["results"].append(dict(acc(d["y"].values, pf, "all"), model="final_in_sample"))
    # long decision threshold below long_s (the model under-predicts agent SQL): LOTO long recall / precision
    yl = d["y"].values >= LONG_S
    rep["long_decision"] = []
    for th in (0.5, 0.75, 1.0, 1.5, 2.0):
        for ten in ("all", "tpch_sf100"):
            m = np.ones(len(d), bool) if ten == "all" else (d["tenant"] == ten).values
            pl_ = (10 ** pl[m]) >= th
            rep["long_decision"].append(dict(th=th, subset=ten, model="g2+agent_loto",
                                             recall=round(float((pl_ & yl[m]).sum() / max(1, yl[m].sum())), 3),
                                             precision=round(float((pl_ & yl[m]).sum() / max(1, pl_.sum())), 3)))
    for r in rep["long_decision"]:
        print("long decision", r)
    model = dict(feats_log=G.LOGF, feats_raw=G.RAWF, mu=mu.tolist(), sd=sd.tolist(), b=b.tolist(),
                 short_s=SHORT_S, long_s=LONG_S, long_decide_s=a.long_decide_s, trained_on=dict(g2=a.g2, agent=a.calib, n_g2=int(len(X2)),
                                                                n_agent=int(len(Xa))))
    if a.model_out:
        json.dump(model, open(a.model_out, "w"), indent=1)
    json.dump(rep, open(a.report, "w"), indent=1)
    for r in rep["results"]:
        print(r["model"], r["subset"], "n", r["n"], "acc", r["acc"], "rho", r["rho"], "long R/P", r["long_recall"],
              r["long_precision"], "true", r["true_counts"])


# ---------------------------------------------------------------------------------------------------- run
def pct(v, q):
    return round(float(np.percentile(v, q)), 3) if len(v) else None


async def run_arm(a, arm, k, trace, tools, dbsched):
    arm, _, th = arm.partition(":")  # e.g. "explain:16" = explain with DuckDB threads 16 (per instance)
    tools.THREADS = int(th) if th else 8
    kw = dict(long_cap=a.long_cap, heavy_cap=a.heavy_cap, order=a.order, starve_s=a.starve_s,
              model_path=a.model or None, log_path=os.path.join(a.out, f"dbsched_{k}_{arm}{'_t' + th if th else ''}.jsonl"))
    ex = dbsched.make_executor(arm, workers=a.db_workers, **({} if arm == "off" else kw))
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ex)
    tag = f"{k}_{arm}" + (f"_t{th}" if th else "")
    calls_f = open(os.path.join(a.out, f"calls_{tag}.jsonl"), "w")
    tasks_out = []
    t0 = time.monotonic()
    t0e = time.time()
    nxt = [0]
    inflight = {}

    async def one_task(i, t):
        st = time.monotonic()
        rec = dict(i=i, key=t["key"], template_id=t["template_id"], tenant=t["tenant"], start_s=round(st - t0, 3),
                   measured=a.warm_s <= st - t0 < a.arm_s, llm_s=0.0, db_wall_s=0.0, db_s=0.0, n_sql=0,
                   timeouts=0, status="done")
        inflight[i] = (st, rec)
        dbsched.TASK.set((f"r{i:05d}", t0e + (st - t0)))
        try:
            for turn in t["turns"]:
                g = turn["llm_s"] * a.gap_scale
                await asyncio.sleep(g)
                rec["llm_s"] += g
                for name, args, _rt, _err in turn["tools"]:
                    tw = time.monotonic()
                    _, info = await asyncio.to_thread(tools.call, t["db_path"], name, args)
                    w = time.monotonic() - tw
                    rec["db_wall_s"] += w
                    rec["db_s"] += info["runtime_s"]
                    rec["n_sql"] += name == "execute_sql"
                    rec["timeouts"] += info["error"] == "timeout"
                    calls_f.write(json.dumps(dict(i=i, tool=name, start_s=round(tw - t0, 3), wall_s=round(w, 4),
                                                  runtime_s=round(info["runtime_s"], 4), error=info["error"],
                                                  measured=rec["measured"],
                                                  sql_id=hashlib.sha1((info["sql"] or "").encode()).hexdigest()[:12]
                                                  if name == "execute_sql" else None)) + "\n")
        except asyncio.CancelledError:
            rec["status"] = "cut"
        rec["e2e_s"] = round(time.monotonic() - st, 3)
        inflight.pop(i, None)
        tasks_out.append(rec)

    async def agent(j):
        while time.monotonic() - t0 < a.arm_s:
            i = nxt[0]; nxt[0] += 1
            await one_task(i, trace[i % len(trace)])

    async def opener():
        rng = np.random.default_rng(a.seed)
        jobs, t = [], 0.0
        while True:
            t += rng.exponential(60.0 / a.rate)
            if t >= a.arm_s:
                break
            await asyncio.sleep(max(0.0, t0 + t - time.monotonic()))
            i = nxt[0]; nxt[0] += 1
            jobs.append(asyncio.create_task(one_task(i, trace[i % len(trace)])))
        await asyncio.gather(*jobs)

    runners = [asyncio.create_task(agent(j)) for j in range(a.agents)] if not a.rate else [asyncio.create_task(opener())]
    await asyncio.sleep(a.arm_s)
    _, pending = await asyncio.wait(runners, timeout=a.drain_s)
    for p in pending:
        p.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    t_end = time.monotonic()
    # running DuckDB calls cannot be cancelled: wait for them (<= 60 s timeout) before the next arm
    await loop.run_in_executor(cf_pool(), ex.shutdown)
    calls_f.close()
    sched_sum = ex.summary() if hasattr(ex, "summary") else None
    with open(os.path.join(a.out, f"tasks_{tag}.jsonl"), "w") as f:
        for r in sorted(tasks_out, key=lambda r: r["i"]):
            f.write(json.dumps(r) + "\n")
    m = [r for r in tasks_out if r["measured"]]
    e2e = [r["e2e_s"] for r in m]
    dbw = [r["db_wall_s"] for r in m]
    calls = [json.loads(l) for l in open(os.path.join(a.out, f"calls_{tag}.jsonl"))]
    sq = [c for c in calls if c["measured"] and c["tool"] == "execute_sql"]
    s = dict(arm=arm, threads=tools.THREADS, k=k, n_measured=len(m), cut=sum(r["status"] == "cut" for r in m),
             task_p50=pct(e2e, 50), task_p95=pct(e2e, 95), task_mean=round(float(np.mean(e2e)), 3) if e2e else None,
             db_wall_p50=pct(dbw, 50), db_wall_mean=round(float(np.mean(dbw)), 3) if dbw else None,
             llm_mean=round(float(np.mean([r["llm_s"] for r in m])), 3) if m else None,
             throughput_per_min=round(len([r for r in tasks_out if r["measured"] and r["status"] == "done"])
                                      / ((a.arm_s - a.warm_s) / 60), 2),
             sql_n=len(sq), sql_wall_p50=pct([c["wall_s"] for c in sq], 50),
             sql_wall_p95=pct([c["wall_s"] for c in sq], 95),
             sql_wall_mean=round(float(np.mean([c["wall_s"] for c in sq])), 3) if sq else None,
             sql_timeouts=sum(c["error"] == "timeout" for c in sq), arm_wall_s=round(t_end - t0, 1),
             sched=sched_sum)
    print(json.dumps({x: y for x, y in s.items() if x != "sched"}), flush=True)
    return s


def cf_pool():
    import concurrent.futures as cf
    return cf.ThreadPoolExecutor(1)


async def cmd_run_async(a):
    import tools_duckdb as tools
    import dbsched
    trace = [t for t in json.load(open(a.trace)) if not a.db or t["tenant"] in a.db.split(",")]
    print(f"{len(trace)} trace tasks ({a.db or 'all'}); arms {a.arms}; agents {a.agents} rate {a.rate}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    json.dump(vars(a), open(os.path.join(a.out, "config.json"), "w"), indent=1)
    if a.prewarm_s:
        print(f"prewarm {a.prewarm_s}s (off, not measured)", flush=True)
        b = argparse.Namespace(**vars(a)); b.arm_s, b.warm_s = a.prewarm_s, a.prewarm_s
        await run_arm(b, "off", 0, trace[::-1], tools, dbsched)
    res = []
    for k, arm in enumerate(a.arms.split(","), 1):
        res.append(await run_arm(a, arm, k, trace, tools, dbsched))
        json.dump(res, open(os.path.join(a.out, "summary.json"), "w"), indent=1)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("extract")
    e.add_argument("--runs", default="/pscratch/sd/a/ap2568/dbkv/runs/p1")
    e.add_argument("--cells", default="")
    e.add_argument("--out", required=True)
    c = sp.add_parser("calib")
    c.add_argument("--trace", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--procs", type=int, default=3)
    c.add_argument("--timeout", type=float, default=15.0)
    c.add_argument("--budget-s", type=float, default=600.0)
    c.add_argument("--quota", default="tpch_sf100=400,tpcds_sf10=150,tpch_sf10=100")
    f = sp.add_parser("fit")
    f.add_argument("--calib", required=True)
    f.add_argument("--g2", default="/pscratch/sd/a/ap2568/dbkv/runs/g2/60826277/results.csv")
    f.add_argument("--model-out", default="")
    f.add_argument("--report", required=True)
    f.add_argument("--long-decide-s", type=float, default=1.0, help="predicted s above which a query is long")
    r = sp.add_parser("run")
    r.add_argument("--trace", required=True)
    r.add_argument("--db", default="tpch_sf100", help="tenants to replay (comma list; empty = all)")
    r.add_argument("--arms", default="off,explain,off")
    r.add_argument("--agents", type=int, default=32)
    r.add_argument("--rate", type=float, default=0.0, help="open-loop tasks/min instead of closed-loop agents")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--arm-s", type=float, default=390.0)
    r.add_argument("--warm-s", type=float, default=60.0)
    r.add_argument("--drain-s", type=float, default=90.0)
    r.add_argument("--prewarm-s", type=float, default=0.0)
    r.add_argument("--gap-scale", type=float, default=1.0)
    r.add_argument("--db-workers", type=int, default=32)
    r.add_argument("--long-cap", type=int, default=2)
    r.add_argument("--heavy-cap", type=int, default=6)
    r.add_argument("--order", default="taskstart")
    r.add_argument("--starve-s", type=float, default=30.0)
    r.add_argument("--model", default="")
    r.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "extract":
        cmd_extract(a)
    elif a.cmd == "calib":
        cmd_calib(a)
    elif a.cmd == "fit":
        cmd_fit(a)
    else:
        asyncio.run(cmd_run_async(a))


if __name__ == "__main__":
    main()
