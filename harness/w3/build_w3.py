"""Workload W3 (PLAN 2j Phase 0 (e)): the SQL agent on DuckDB analytics data, TPC-H SF10/SF100 + TPC-DS SF10,
with executable gold SQL and fixed-seed streams. CPU only; run in a CPU Slurm job (slurm/w3_build.sbatch).

  python harness/w3/build_w3.py bank    [--draws 6] [--workers 4] [--threads 8] [--only t01,h05]
  python harness/w3/build_w3.py streams [--n 1000] [--seeds 0 1 2 3 4]

Templates: the W2 pool (harness/plancache: 99 TPC-DS + 22 TPC-H, each with typed slots and 4 phrasings), unchanged.

Stage "bank": for every (template, tenant) pair (TPC-H templates on tpch_sf10 and tpch_sf100, TPC-DS templates on
tpcds_sf10) draw --draws parameter sets (seeded by template, tenant and draw index), render the gold SQL and run it
TWICE under the agent's own DuckDB caps (read-only, memory_limit 16GB, --threads threads; first run with --threads,
second with half as many, so a thread-count-dependent tie order shows up). An instance is KEPT iff
  - both runs succeed within the agent's tool timeout (60 s each),
  - the result is non-empty and has <= MAX_ROWS rows,
  - the two runs give the same row set after canonicalization (see canon()).
Every attempt, kept or not, goes to bank/attempts.jsonl with its reason. Kept instances go to bank/bank.jsonl with
their canonical gold rows, so GPU jobs grade without re-running SF100 gold queries.

Stage "streams": fixed-seed JSONL streams, drawn only from kept instances.
  mix   tenant first, weights tpcds_sf10 0.50 / tpch_sf10 0.25 / tpch_sf100 0.25; then a template uniformly among
        the tenant's usable templates; then a kept instance and a phrasing uniformly.
  h100  TPC-H SF100 only (for option D, "32 agents on SF100").
Record fields (a superset of the W stream format run_w.py reads): qid, pos, tenant, db_path, bench, template_id,
phrasing_id, params, question, evidence (""), gold_sql, gold_rows (canonical), gold_ncols, gold_runtime_s,
is_repeat (template seen earlier in the stream; information only), complexity, instance.

canon(): rows -> sorted list of lists of canonical values; numbers (int, float, Decimal) -> float formatted with
'.10g' (so 1.5, Decimal('1.50') and 1.5000000001 compare equal, as Python's own Decimal/float equality would for the
first two); dates/times -> ISO strings; None -> None; everything else -> str. Grading compares canon(pred) with the
stored gold rows as sets of tuples (the agent port uses the same function).

Outputs: $DBKV_DATA/w3/bank/{attempts,bank}.jsonl, bank/summary.json; $DBKV_DATA/w3/streams/w3_<variant>_s<seed>.jsonl,
streams/summary.json.
"""
import argparse, datetime as dt, decimal, hashlib, json, os, random, sys, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plancache"))
import templates as T  # noqa: E402
from make_streams_w2 import load_pool, bench_of  # noqa: E402

DATA = os.environ.get("DBKV_DATA", os.path.expandvars("$SCRATCH/dbkv"))
OUT = os.path.join(DATA, "w3")
TENANTS = {"tpch_sf10": os.path.join(DATA, "tpch", "tpch_sf10.duckdb"),
           "tpch_sf100": os.path.join(DATA, "tpch", "tpch_sf100.duckdb"),
           "tpcds_sf10": os.path.join(DATA, "tpcds", "tpcds_sf10.duckdb")}
BENCH_TENANTS = {"tpch": ["tpch_sf10", "tpch_sf100"], "tpcds": ["tpcds_sf10"]}
VARIANTS = {"mix": {"tpcds_sf10": 0.50, "tpch_sf10": 0.25, "tpch_sf100": 0.25},
            "h100": {"tpch_sf100": 1.0}}
TIMEOUT_S = 60.0     # the agent's execute_sql timeout (tools_duckdb.TIMEOUT_S)
MAX_ROWS = 1000
MEM = "16GB"         # PLAN 4a cap, as in tools_duckdb.connect


def canon_val(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float, decimal.Decimal)):
        return format(float(v), ".10g")
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    return str(v)


def canon(rows):
    return sorted(([canon_val(v) for v in r] for r in rows), key=lambda r: json.dumps(r))


def run(con, sql):
    timer = threading.Timer(TIMEOUT_S, con.interrupt)
    timer.daemon = True
    t = time.monotonic()
    timer.start()
    try:
        cur = con.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
        return rows, len(cur.description or []), time.monotonic() - t, None
    except Exception as e:  # noqa: BLE001
        return None, 0, time.monotonic() - t, f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        timer.cancel()


def bank_pair(tid, tenant, draws, threads):
    """Validate `draws` instances of template tid on tenant. Runs in a worker process."""
    import duckdb
    tpls, _ = load_pool(verbose=False)
    tpl = {t["id"]: t for t in tpls}[tid]
    con = duckdb.connect(TENANTS[tenant], read_only=True)
    con.execute(f"SET memory_limit='{MEM}'")
    out = []
    for k in range(draws):
        rng = random.Random(f"W3-bank-{tid}-{tenant}-{k}")
        rec = dict(template_id=tid, tenant=tenant, instance=k, bench=bench_of(tpl), complexity=tpl.get("complexity"))
        try:
            params = T.draw_params(tpl, rng, con, tenant)
            _, sql = T.render(tpl, params, 0)
        except Exception as e:  # noqa: BLE001
            out.append(dict(rec, kept=False, reason=f"draw_error: {type(e).__name__}: {str(e)[:200]}"))
            continue
        rec.update(params=params, gold_sql=sql)
        con.execute(f"SET threads={threads}")
        r1, nc, t1, e1 = run(con, sql)
        if e1:
            reason = "timeout" if "INTERRUPT" in e1.upper() else "error"
            out.append(dict(rec, kept=False, reason=reason, error=e1, runtime_s=round(t1, 3)))
            continue
        if not r1:
            out.append(dict(rec, kept=False, reason="empty", runtime_s=round(t1, 3)))
            continue
        if len(r1) > MAX_ROWS:
            out.append(dict(rec, kept=False, reason=f"rows>{MAX_ROWS}", runtime_s=round(t1, 3)))
            continue
        con.execute(f"SET threads={max(1, threads // 2)}")
        r2, _, t2, e2 = run(con, sql)
        if e2:
            out.append(dict(rec, kept=False, reason="rerun_error", error=e2, runtime_s=round(t1, 3)))
            continue
        c1, c2 = canon(r1), canon(r2 or [])
        if c1 != c2:
            out.append(dict(rec, kept=False, reason="nondeterministic", runtime_s=round(t1, 3)))
            continue
        h = hashlib.sha256(json.dumps(c1).encode()).hexdigest()[:16]
        out.append(dict(rec, kept=True, reason="ok", runtime_s=round(t1, 3), rerun_s=round(t2, 3), nrows=len(c1),
                        ncols=nc, gold_rows=c1, gold_hash=h))
    con.close()
    return out


def stage_bank(a):
    tpls, info = load_pool(verbose=True)
    if not info["complete"]:
        sys.exit(f"W2 pool incomplete: {info['by_bench']}")
    pairs = [(t["id"], ten) for t in tpls for ten in BENCH_TENANTS[bench_of(t)]]
    if a.only:
        keep = set(a.only.split(","))
        pairs = [p for p in pairs if p[0] in keep]
    # SF100 pairs first: they are the slow ones
    pairs.sort(key=lambda p: (p[1] != "tpch_sf100", p))
    d = os.path.join(OUT, "bank" if not a.only else "bank_dev")
    os.makedirs(d, exist_ok=True)
    print(f"{len(pairs)} (template, tenant) pairs x {a.draws} draws; workers {a.workers} x threads {a.threads}", flush=True)
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(a.workers) as ex:
        futs = {ex.submit(bank_pair, tid, ten, a.draws, a.threads): (tid, ten) for tid, ten in pairs}
        for i, f in enumerate(as_completed(futs), 1):
            tid, ten = futs[f]
            try:
                res = f.result()
            except Exception as e:  # noqa: BLE001
                res = [dict(template_id=tid, tenant=ten, instance=-1, kept=False, reason=f"worker_error: {e}")]
            results.extend(res)
            nk = sum(r["kept"] for r in res)
            print(f"[{i}/{len(pairs)} {time.time() - t0:6.0f}s] {tid:>4} {ten:<11} kept {nk}/{len(res)} "
                  f"{Counter(r['reason'] for r in res if not r['kept'])}", flush=True)
    results.sort(key=lambda r: (r["template_id"], r["tenant"], r["instance"]))
    with open(os.path.join(d, "attempts.jsonl"), "w") as f:
        for r in results:
            f.write(json.dumps({k: v for k, v in r.items() if k != "gold_rows"}, default=str) + "\n")
    kept = [r for r in results if r["kept"]]
    with open(os.path.join(d, "bank.jsonl"), "w") as f:
        for r in kept:
            f.write(json.dumps(r, default=str) + "\n")
    per_pair = defaultdict(int)
    for r in kept:
        per_pair[(r["template_id"], r["tenant"])] += 1
    by_tenant = {ten: dict(pairs=sum(1 for p in pairs if p[1] == ten),
                           usable_templates=sum(1 for (tid, t2), n in per_pair.items() if t2 == ten and n > 0),
                           kept=sum(1 for r in kept if r["tenant"] == ten),
                           reasons=dict(Counter(r["reason"] for r in results if r["tenant"] == ten)),
                           runtime_s_p50=_pct([r["runtime_s"] for r in kept if r["tenant"] == ten], 50),
                           runtime_s_p90=_pct([r["runtime_s"] for r in kept if r["tenant"] == ten], 90),
                           runtime_s_max=max([r["runtime_s"] for r in kept if r["tenant"] == ten], default=None))
                 for ten in TENANTS}
    unusable = sorted(f"{tid}@{ten}" for tid, ten in pairs if per_pair[(tid, ten)] == 0)
    summ = dict(draws=a.draws, threads=a.threads, timeout_s=TIMEOUT_S, max_rows=MAX_ROWS, memory_limit=MEM,
                attempts=len(results), kept=len(kept), by_tenant=by_tenant, unusable_pairs=unusable,
                wall_s=round(time.time() - t0, 1))
    json.dump(summ, open(os.path.join(d, "summary.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != "unusable_pairs"}, indent=1))
    print(f"unusable pairs ({len(unusable)}): {unusable}")


def _pct(v, q):
    if not v:
        return None
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q / 100 * len(v)))], 3)


def stage_streams(a):
    tpls, _ = load_pool(verbose=False)
    by_id = {t["id"]: t for t in tpls}
    bank = [json.loads(l) for l in open(os.path.join(OUT, "bank", "bank.jsonl"))]
    inst = defaultdict(list)
    for r in bank:
        inst[(r["tenant"], r["template_id"])].append(r)
    d = os.path.join(OUT, "streams")
    os.makedirs(d, exist_ok=True)
    summ = {}
    for var, weights in VARIANTS.items():
        tenants = sorted(weights)
        usable = {ten: sorted(tid for (t2, tid) in inst if t2 == ten) for ten in tenants}
        for seed in a.seeds:
            rng = random.Random(f"W3-{var}-s{seed}")
            rows, seen = [], set()
            for i in range(a.n):
                ten = rng.choices(tenants, weights=[weights[t] for t in tenants])[0]
                tid = rng.choice(usable[ten])
                r = rng.choice(inst[(ten, tid)])
                tpl = by_id[tid]
                ph = rng.randrange(len(tpl["phrasings"]))
                question, sql = T.render(tpl, r["params"], ph)
                assert sql == r["gold_sql"], (tid, ten)
                rows.append(dict(qid=f"w3{var}-s{seed}-{i:04d}", pos=i, tenant=ten, db_path=TENANTS[ten],
                                 bench=r["bench"], template_id=tid, phrasing_id=ph, params=r["params"],
                                 question=question, evidence="", gold_sql=sql, gold_rows=r["gold_rows"],
                                 gold_ncols=r["ncols"], gold_runtime_s=r["runtime_s"], is_repeat=tid in seen,
                                 complexity=r["complexity"], instance=r["instance"]))
                seen.add(tid)
            name = f"w3_{var}_s{seed}"
            with open(os.path.join(d, name + ".jsonl"), "w") as f:
                f.writelines(json.dumps(x, default=str) + "\n" for x in rows)
            gr = [x["gold_runtime_s"] for x in rows]
            summ[name] = dict(n=len(rows), tenants=dict(Counter(x["tenant"] for x in rows)),
                              distinct_templates=len({x["template_id"] for x in rows}),
                              repeat_rate=round(sum(x["is_repeat"] for x in rows) / len(rows), 3),
                              repeat_rate_first100=round(sum(x["is_repeat"] for x in rows[:100]) / min(100, len(rows)), 3),
                              complexity=dict(Counter(str(x["complexity"]) for x in rows)),
                              gold_runtime_s_p50=_pct(gr, 50), gold_runtime_s_p90=_pct(gr, 90),
                              usable_templates={t: len(usable[t]) for t in tenants})
            print(name, json.dumps(summ[name]), flush=True)
    json.dump(summ, open(os.path.join(d, "summary.json"), "w"), indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["bank", "streams"])
    ap.add_argument("--draws", type=int, default=6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--only", default="", help="comma list of template ids (dev; writes bank_dev/)")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    a = ap.parse_args()
    stage_bank(a) if a.stage == "bank" else stage_streams(a)


if __name__ == "__main__":
    main()
