"""G2 runner: for each generated query, time EXPLAIN (FORMAT JSON), parse optimizer estimates,
then run the query (1 warm-up + N timed runs) under the deployment caps, with a timeout.

  python calib/g2_run.py --db $DBKV_DATA/tpch/tpch_sf1.duckdb [--db ...] --out $DBKV_DATA/runs/g2/<id>

Writes <out>/results.csv (one row per query, appended as it goes) and <out>/queries_<db>.jsonl.
Run it on a compute node: it executes the workload.
"""
import argparse, csv, json, math, os, random, re, sys, threading, time

import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g2_queries import generate  # noqa: E402

FEATS = ["root_ec", "sum_ec", "max_ec", "logsum_ec", "scan_ec_sum", "scan_base_rows", "max_base_rows",
         "join_ec_sum", "max_join_ec", "agg_in_ec", "n_ops", "n_scans", "n_joins", "n_aggs", "n_filters",
         "n_order", "n_topn", "n_window", "n_cte", "depth", "n_ec_missing"]
COLS = (["run_id", "db", "db_kind", "sf", "qid", "template", "family", "status", "censored",
         "explain_ms", "explain_ms2"] + FEATS +
        ["warmup_s", "t1_s", "t2_s", "t3_s", "median_s", "nrows", "error"])

_NUM = re.compile(r"\d+")


def _ec(info):
    v = info.get("Estimated Cardinality")
    if v is None:
        return None
    m = _NUM.search(str(v).replace(",", ""))
    return int(m.group(0)) if m else None


def plan_features(plan_roots, base_rows):
    f = dict.fromkeys(FEATS, 0.0)
    ecs = []

    def walk(n, d):
        name = n.get("name", "").upper()
        info = n.get("extra_info", {}) or {}
        ec = _ec(info)
        f["n_ops"] += 1
        f["depth"] = max(f["depth"], d)
        if ec is None:
            f["n_ec_missing"] += 1
        else:
            ecs.append(ec)
        kids = n.get("children", []) or []
        if "SCAN" in name:
            f["n_scans"] += 1
            f["scan_ec_sum"] += ec or 0
            t = str(info.get("Table", "")).split(".")[-1]
            br = base_rows.get(t, 0)
            f["scan_base_rows"] += br
            f["max_base_rows"] = max(f["max_base_rows"], br)
            if info.get("Filters"):
                f["n_filters"] += 1
        if "JOIN" in name or "CROSS_PRODUCT" in name:
            f["n_joins"] += 1
            f["join_ec_sum"] += ec or 0
            f["max_join_ec"] = max(f["max_join_ec"], ec or 0)
        if "GROUP_BY" in name or "AGGREGATE" in name:
            f["n_aggs"] += 1
            f["agg_in_ec"] += sum(_ec(k.get("extra_info", {}) or {}) or 0 for k in kids)
        if name == "FILTER":
            f["n_filters"] += 1
        if name in ("ORDER_BY",):
            f["n_order"] += 1
        if "TOP_N" in name:
            f["n_topn"] += 1
        if "WINDOW" in name:
            f["n_window"] += 1
        if "CTE" in name:
            f["n_cte"] += 1
        for k in kids:
            walk(k, d + 1)

    for root in plan_roots:
        walk(root, 1)
    # root EC: first estimate found on the leftmost path from the top
    n = plan_roots[0] if plan_roots else {}
    while n:
        e = _ec(n.get("extra_info", {}) or {})
        if e is not None:
            f["root_ec"] = e
            break
        n = (n.get("children") or [None])[0]
    f["sum_ec"] = float(sum(ecs))
    f["max_ec"] = float(max(ecs)) if ecs else 0.0
    f["logsum_ec"] = float(sum(math.log1p(e) for e in ecs))
    return f


def explain(con, sql):
    t = time.perf_counter()
    rows = con.execute("EXPLAIN (FORMAT JSON) " + sql).fetchall()
    ms = (time.perf_counter() - t) * 1e3
    roots = []
    for r in rows:
        roots += json.loads(r[1])
    return ms, roots


def timed(con, sql, timeout):
    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    t = time.perf_counter()
    try:
        rows = con.execute(sql).fetchall()
        return time.perf_counter() - t, len(rows), None
    except duckdb.InterruptException:
        return None, None, "timeout"
    finally:
        timer.cancel()


def connect(path, a):
    con = duckdb.connect(path, read_only=True)
    con.execute(f"SET memory_limit='{a.memory_limit}'")
    con.execute(f"SET threads={a.threads}")
    if a.temp_dir:
        os.makedirs(a.temp_dir, exist_ok=True)
        con.execute(f"SET temp_directory='{a.temp_dir}'")
    return con


def run_db(path, a, writer, fh):
    t_start = time.time()
    name = os.path.splitext(os.path.basename(path))[0]
    con = connect(path, a)
    t0 = time.perf_counter()
    kind, sf, qs = generate(con, seed=a.seed, tpch_instances=a.tpch_instances,
                            tpcds_instances=a.tpcds_instances, probes_per_family=a.probes_per_family)
    print(f"[{name}] kind={kind} sf={sf} generated {len(qs)} queries in {time.perf_counter() - t0:.1f}s",
          flush=True)
    with open(os.path.join(a.out, f"queries_{name}.jsonl"), "w") as qf:
        for q in qs:
            qf.write(json.dumps(q, default=str) + "\n")
    base_rows = dict(con.execute("select table_name, estimated_size from duckdb_tables()").fetchall())
    order = list(range(len(qs)))
    random.Random(a.seed + 1).shuffle(order)
    if a.limit:
        order = order[:a.limit]
    counts = {"ok": 0, "timeout": 0, "error": 0}
    for i, k in enumerate(order):
        if a.budget_s and time.time() - t_start > a.budget_s:
            print(f"[{name}] budget reached after {i} queries", flush=True)
            break
        q = qs[k]
        row = dict(run_id=a.run_id, db=name, db_kind=kind, sf=sf, qid=q["qid"], template=q["template"],
                   family=q["family"], censored=0, error="")
        try:
            ms, roots = explain(con, q["sql"])
            ms2, _ = explain(con, q["sql"])
            row.update(explain_ms=round(ms, 3), explain_ms2=round(ms2, 3))
            row.update(plan_features(roots, base_rows))
            ts, status, nrows = [], "ok", None
            for j in range(a.reps + 1):
                s, nrows_j, err = timed(con, q["sql"], a.timeout)
                if err:
                    status = "timeout"
                    break
                nrows = nrows_j
                if j == 0:
                    row["warmup_s"] = round(s, 6)
                else:
                    ts.append(s)
            for j, s in enumerate(ts[:3]):
                row[f"t{j + 1}_s"] = round(s, 6)
            if status == "timeout":
                row.update(censored=1, median_s=a.timeout)
            else:
                ts.sort()
                row["median_s"] = round(ts[len(ts) // 2], 6)
            row.update(status=status, nrows=nrows)
        except duckdb.InterruptException:
            row.update(status="timeout", censored=1, median_s=a.timeout)
        except Exception as e:  # noqa: BLE001
            row.update(status="error", error=f"{type(e).__name__}: {str(e)[:200]}".replace("\n", " "))
        counts[row["status"]] += 1
        writer.writerow(row)
        fh.flush()
        if (i + 1) % 50 == 0:
            print(f"[{name}] {i + 1}/{len(order)} {counts} elapsed {time.time() - t_start:.0f}s", flush=True)
    print(f"[{name}] done {counts}", flush=True)
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="append", required=True, help="DuckDB file (repeatable); opened read-only")
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", dest="run_id", default=None)
    ap.add_argument("--timeout", type=float, default=60.0, help="per-execution timeout (s); censored")
    ap.add_argument("--reps", type=int, default=3, help="timed runs after 1 warm-up")
    ap.add_argument("--memory-limit", dest="memory_limit", default="16GB")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--temp-dir", dest="temp_dir", default=None, help="spill dir (default <out>/tmp)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tpch-instances", dest="tpch_instances", type=int, default=20)
    ap.add_argument("--tpcds-instances", dest="tpcds_instances", type=int, default=5)
    ap.add_argument("--probes-per-family", dest="probes_per_family", type=int, default=80)
    ap.add_argument("--limit", type=int, default=0, help="run only the first N (shuffled) queries per db")
    ap.add_argument("--budget-s", dest="budget_s", type=float, default=0, help="per database: stop starting new queries after this many seconds")
    a = ap.parse_args()
    a.run_id = a.run_id or os.path.basename(os.path.normpath(a.out))
    a.temp_dir = a.temp_dir or os.path.join(a.out, "tmp")
    os.makedirs(a.out, exist_ok=True)
    json.dump(vars(a), open(os.path.join(a.out, "config.json"), "w"), indent=1)
    path = os.path.join(a.out, "results.csv")
    new = not os.path.exists(path)
    t_start = time.time()
    print(f"duckdb {duckdb.__version__}; caps memory_limit={a.memory_limit} threads={a.threads}", flush=True)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        if new:
            w.writeheader()
        for db in a.db:
            run_db(db, a, w, fh)
    print(f"total {time.time() - t_start:.0f}s -> {path}", flush=True)


if __name__ == "__main__":
    main()
