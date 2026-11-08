"""Write the W2 question streams (PLAN §2i, Test P2). CPU only; run inside an srun job (opens the tenant DBs).

  python harness/plancache/make_streams_w2.py                    # full pool (121) and TPC-DS-only pool (99)
  python harness/plancache/make_streams_w2.py --pool all         # only the 121-template streams
  python harness/plancache/make_streams_w2.py --allow-partial    # development: whatever template modules exist

Template pool (121 = 99 TPC-DS + 22 TPC-H):
  templates.TEMPLATES                     the 30 W templates, unchanged (bench "tpcds")
  templates._ALL t25 / t82 / t91          the 3 templates excluded from W "return" (§2i); a W2 module may supply its
                                          own version of these ids instead, which then takes precedence
  templates_w2_ds_a.TEMPLATES, templates_w2_ds_b.TEMPLATES   new TPC-DS templates (bench "tpcds")
  templates_w2_h.TEMPLATES                TPC-H h01..h22 (bench "tpch")
All are templates.py-format dicts, drawn and rendered with templates.draw_params / templates.render. Without
--allow-partial the pool must be exactly 121 (99 tpcds + 22 tpch) or the script stops.

Tenants: tpcds -> $DBKV_DATA/tenants/tpcds_sf{0.5,1,2,5}.duckdb (tenant keys sf0.5 / sf1 / sf2 / sf5, as in W);
tpch -> $DBKV_DATA/tpch/tpch_sf{1,10}.duckdb (tenant keys tpch_sf1 / tpch_sf10). The tenant is drawn uniformly
among the template's benchmark tenants. "db" / "db_sample" slots are resolved by templates.db_values against that
tenant's connection (cache key = tenant key + sql, so TPC-H and TPC-DS values never mix). DBs are opened
read_only with threads = 4.

Streams: 150 questions, STRICT repeat definition (is_repeat = template appeared anywhere earlier in the stream).
The repeat/new schedule is make_streams.schedule (|#repeats - r*(i+1)| < 1 for every prefix, position 0 new).
A repeat picks uniformly among the templates seen so far; a new question picks uniformly among the pool's unseen
templates. Then tenant, parameters and phrasing are drawn (same draw order as make_streams.py).
Rates 20 / 50 / 80; seeds 0, 2, 3, 4 (evaluation) and 1, 5 (calibration). RNG seed string "W2-<pool>-r<rate>-s<seed>".
TPC-DS-only pool (§2i "also reported"): the same generator restricted to the 99 TPC-DS templates. r20 needs 120
new templates > 99, so the TPC-DS-only r20 streams are infeasible and are not written (recorded in summary.json).

Outputs ($DBKV_DATA/plancache/w2/; with --allow-partial under w2/dev_partial/ instead):
  streams/w2_r{20,50,80}_s{0..5}.jsonl          full pool
  streams_tpcds/w2ds_r{50,80}_s{0..5}.jsonl     TPC-DS-only pool
  <dir>/summary.json                            pool, realized strict rates per prefix, max prefix deviation, mixes
Record fields: qid, pos, tenant, db_path, template_id, phrasing_id, params, question, evidence (""), gold_sql,
is_repeat, gap (positions since the template last appeared, null if new), complexity, bench.
"""
import argparse, importlib, json, os, random, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import templates as T  # noqa: E402
from make_streams import schedule  # noqa: E402

DATA = os.environ.get("DBKV_DATA", "/pscratch/sd/a/ap2568/dbkv")
OUT = os.path.join(DATA, "plancache", "w2")
TENANTS = {"tpcds": ["sf0.5", "sf1", "sf2", "sf5"], "tpch": ["tpch_sf1", "tpch_sf10"]}
RATES = [20, 50, 80]
EVAL_SEEDS = [0, 2, 3, 4]
CAL_SEEDS = [1, 5]
SEEDS = sorted(EVAL_SEEDS + CAL_SEEDS)
N = 150
W2_MODULES = ["templates_w2_ds_a", "templates_w2_ds_b", "templates_w2_h"]
RETURNING = ["t25", "t82", "t91"]
EXPECTED = {"tpcds": 99, "tpch": 22}
POOLS = {"all": ("w2", "streams"), "tpcds": ("w2ds", "streams_tpcds")}


def db_path(tenant):
    if tenant.startswith("tpch_"):
        return os.path.join(DATA, "tpch", f"{tenant}.duckdb")
    return os.path.join(DATA, "tenants", f"tpcds_{tenant}.duckdb")


def bench_of(tpl):
    return tpl.get("bench", "tpcds")


def load_pool(verbose=True, tolerant=False):
    """(list of templates sorted by id, info dict). Raises on duplicate / malformed templates.
    tolerant (development only): a module that fails to import is reported as missing instead of raising."""
    pool, origin = {}, {}
    for t in T.TEMPLATES:
        pool[t["id"]] = t; origin[t["id"]] = "templates.TEMPLATES"
    found, missing_mods = [], []
    module_ids = {}
    for name in W2_MODULES:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name != name and not tolerant:
                raise
            missing_mods.append(name)
            continue
        except Exception as e:  # noqa: BLE001  (a module still being written)
            if not tolerant:
                raise
            print(f"WARNING: {name} failed to import ({type(e).__name__}: {e}); treated as missing", flush=True)
            missing_mods.append(name)
            continue
        tpls = getattr(mod, "TEMPLATES", None)
        if tpls is None:
            tpls = getattr(mod, "_ALL")
        found.append(name)
        for t in tpls:
            tid = t["id"]
            if tid in module_ids:
                raise ValueError(f"duplicate template id {tid} in {name} and {module_ids[tid]}")
            if tid in pool:
                raise ValueError(f"{name} redefines W template {tid} (the 30 W templates are kept as they are)")
            module_ids[tid] = name
    for name in found:
        mod = sys.modules[name]
        for t in (getattr(mod, "TEMPLATES", None) or getattr(mod, "_ALL")):
            pool[t["id"]] = t; origin[t["id"]] = name
    by_all = {t["id"]: t for t in T._ALL}
    for tid in RETURNING:
        if tid not in pool:
            pool[tid] = by_all[tid]; origin[tid] = "templates._ALL (returning)"
    for tid, t in pool.items():
        b = bench_of(t)
        if b not in TENANTS:
            raise ValueError(f"{tid}: bench {b!r}")
        for k in ("sql", "slots", "phrasings"):
            if k not in t:
                raise ValueError(f"{tid}: missing {k}")
        if len(t["phrasings"]) != 4:
            raise ValueError(f"{tid}: {len(t['phrasings'])} phrasings (expected 4)")
    tpls = [pool[k] for k in sorted(pool)]
    dq = [k for k, n in Counter((bench_of(t), t.get("qnum")) for t in tpls).items() if n > 1]
    if dq:
        raise ValueError(f"duplicate (bench, qnum): {dq}")
    nb = Counter(bench_of(t) for t in tpls)
    missing_q = {b: sorted(set(range(1, n + 1)) - {t.get("qnum") for t in tpls if bench_of(t) == b})
                 for b, n in EXPECTED.items()}
    info = dict(pool_size=len(tpls), by_bench=dict(nb), modules_found=found, modules_missing=missing_mods,
                origin=dict(Counter(origin.values())), ids=[t["id"] for t in tpls], missing_qnums=missing_q,
                complete=(len(tpls) == sum(EXPECTED.values()) and all(nb[b] == n for b, n in EXPECTED.items())
                          and not any(missing_q.values())))
    if verbose:
        print(f"template pool: {len(tpls)} ({dict(nb)}); modules found {found}, missing {missing_mods}; "
              f"origins {info['origin']}; missing qnums {info['missing_qnums']}", flush=True)
    return tpls, info


def make_stream(tpls, pool_name, prefix, rate, seed, cons, allow_fallback=False):
    rng = random.Random(f"W2-{pool_name}-r{rate:02d}-s{seed}")
    by_id = {t["id"]: t for t in tpls}
    ids = sorted(by_id)
    sched = schedule(rate, rng, N)
    last, rows, fallbacks = {}, [], 0
    for i, rep in enumerate(sched):
        seen = sorted(last)
        unseen = [t for t in ids if t not in last]
        if not rep and not unseen:
            if not allow_fallback:
                raise RuntimeError(f"pool of {len(ids)} exhausted at position {i} (r{rate} s{seed})")
            rep, fallbacks = True, fallbacks + 1  # development only: realized rate deviates
        tid = rng.choice(seen) if rep else rng.choice(unseen)
        tpl = by_id[tid]
        tenant = rng.choice(TENANTS[bench_of(tpl)])
        params = T.draw_params(tpl, rng, cons[tenant], tenant)
        ph = rng.randrange(len(tpl["phrasings"]))
        question, sql = T.render(tpl, params, ph)
        rows.append(dict(qid=f"{prefix}-r{rate:02d}s{seed}-{i:04d}", pos=i, tenant=tenant, db_path=db_path(tenant),
                         template_id=tid, phrasing_id=ph, params=params, question=question, evidence="",
                         gold_sql=sql, is_repeat=tid in last, gap=(i - last[tid]) if tid in last else None,
                         complexity=tpl.get("complexity"), bench=bench_of(tpl)))
        assert rows[-1]["is_repeat"] == rep
        last[tid] = i
    return rows, fallbacks


def stream_stats(rows, rate):
    k, dev = 0, 0.0
    for i, r in enumerate(rows):
        k += r["is_repeat"]
        dev = max(dev, abs(k - rate / 100 * (i + 1)))
    return dict(n=len(rows), strict_rate=round(k / len(rows), 4),
                strict_rate_at={n: round(sum(r["is_repeat"] for r in rows[:n]) / n, 4) for n in (30, 50, 100, 150)},
                max_prefix_deviation_questions=round(dev, 4), new_templates=sum(not r["is_repeat"] for r in rows),
                distinct_templates=len({r["template_id"] for r in rows}),
                bench=dict(Counter(r["bench"] for r in rows)), tenants=dict(sorted(Counter(r["tenant"] for r in rows).items())),
                complexity=dict(Counter(str(r["complexity"]) for r in rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-partial", action="store_true", help="development: run on whatever modules exist")
    ap.add_argument("--pool", choices=["all", "tpcds", "both"], default="both")
    a = ap.parse_args()
    tpls_all, info = load_pool(tolerant=a.allow_partial)
    if not info["complete"] and not a.allow_partial:
        sys.exit(f"pool is {info['pool_size']} {info['by_bench']}, need 121 (99 tpcds + 22 tpch); "
                 "use --allow-partial for development")
    base = os.path.join(OUT, "dev_partial") if not info["complete"] else OUT
    import duckdb
    cons = {}
    for tenant in TENANTS["tpcds"] + TENANTS["tpch"]:
        c = duckdb.connect(db_path(tenant), read_only=True)
        c.execute("SET threads=4"); c.execute("SET memory_limit='16GB'")
        cons[tenant] = c
    pools = ["all", "tpcds"] if a.pool == "both" else [a.pool]
    for pool_name in pools:
        prefix, sub = POOLS[pool_name]
        tpls = tpls_all if pool_name == "all" else [t for t in tpls_all if bench_of(t) == "tpcds"]
        out_dir = os.path.join(base, sub)
        os.makedirs(out_dir, exist_ok=True)
        summary = dict(pool=pool_name, pool_size=len(tpls), complete=info["complete"],
                       pool_info={k: v for k, v in info.items() if k != "ids"}, template_ids=[t["id"] for t in tpls],
                       definition="is_repeat = strict (template appeared anywhere earlier in the stream); schedule keeps "
                                  "|#repeats - r*(i+1)| < 1 over every prefix", streams={}, infeasible={})
        for rate in RATES:
            need_new = int(round((1 - rate / 100) * N))
            for seed in SEEDS:
                name = f"{prefix}_r{rate:02d}_s{seed}"
                if need_new > len(tpls) and not a.allow_partial:
                    summary["infeasible"][name] = f"needs ~{need_new} new templates, pool has {len(tpls)}"
                    print(name, "INFEASIBLE:", summary["infeasible"][name], flush=True)
                    continue
                rows, fb = make_stream(tpls, pool_name, prefix, rate, seed, cons, allow_fallback=a.allow_partial)
                with open(os.path.join(out_dir, name + ".jsonl"), "w") as f:
                    f.writelines(json.dumps(r, default=str) + "\n" for r in rows)
                st = stream_stats(rows, rate)
                st["dev_fallbacks_new_to_repeat"] = fb
                summary["streams"][name] = st
                print(name, json.dumps({k: st[k] for k in ("strict_rate", "max_prefix_deviation_questions",
                                                            "new_templates", "bench")}), f"fallbacks={fb}", flush=True)
        json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=1)
        print("wrote", out_dir, flush=True)


if __name__ == "__main__":
    main()
