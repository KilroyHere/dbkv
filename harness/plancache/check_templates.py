"""Template check (run in an srun job): K random parameter draws per template x tenant, executed with 8 threads and
16 GB. Reports the empty-result rate (no rows, or every cell NULL) per template and tenant, and runtimes (the
sf5 max is the >10 s exclusion test).

  python harness/plancache/check_templates.py --k 12 --out $DBKV_DATA/plancache/template_check.json
"""
import argparse, json, os, random, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import templates as T  # noqa: E402
from make_streams import TENANTS, db_path, is_empty  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import duckdb
    out = {}
    for tenant in TENANTS:
        con = duckdb.connect(db_path(tenant), read_only=True)
        con.execute("SET memory_limit='16GB'"); con.execute("SET threads=8")
        for tpl in T.TEMPLATES:
            rng = random.Random(f"check-{tpl['id']}-{tenant}")
            ts, emp = [], 0
            for _ in range(a.k):
                p = T.draw_params(tpl, rng, con, tenant)
                _, sql = T.render(tpl, p, 0)
                t0 = time.perf_counter()
                res = con.execute(sql).fetchall()
                ts.append(time.perf_counter() - t0)
                emp += is_empty(res)
            d = out.setdefault(tpl["id"], dict(complexity=tpl["complexity"], qnum=tpl["qnum"]))
            d[tenant] = dict(empty_rate=round(emp / a.k, 3), median_s=round(sorted(ts)[len(ts) // 2], 3),
                             max_s=round(max(ts), 3))
            print(tenant, tpl["id"], d[tenant], flush=True)
        con.close()
    for d in out.values():
        d["empty_rate_all"] = round(sum(d[t]["empty_rate"] for t in TENANTS) / len(TENANTS), 3)
    json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
