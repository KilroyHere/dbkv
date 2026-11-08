#!/bin/bash
# W tenants (PLAN §2h): TPC-DS at SF 0.5 / 1 / 2 / 5 as DuckDB files in $DBKV_DATA/tenants/tpcds_sf{0.5,1,2,5}.duckdb
# (same schema, different data). SF1 is copied from the existing $DBKV_DATA/tpcds/tpcds_sf1.duckdb.
# Cost: 16 physical cores = 1/8 node-h per hour; SF10 took 26 s with SF1, so expect < 5 min -> < 0.01; --time 0:45 caps at 0.09.
#SBATCH --job-name=tpcds_tenants
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --time=00:45:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
OUT=$DBKV_DATA/tenants; mkdir -p "$OUT" "$DBKV_DATA/tmp"
[[ -f $OUT/tpcds_sf1.duckdb ]] || cp "$DBKV_DATA/tpcds/tpcds_sf1.duckdb" "$OUT/tpcds_sf1.duckdb"
python - "$OUT" <<'PY'
import sys, os, time, duckdb
out = sys.argv[1]
for sf in ("0.5", "2", "5"):
    path = f"{out}/tpcds_sf{sf}.duckdb"; tmp = path + ".partial"
    if os.path.exists(path):
        print(path, "exists"); continue
    for p in (tmp, tmp + ".wal"):
        if os.path.exists(p): os.remove(p)
    con = duckdb.connect(tmp); con.execute("SET threads=32"); con.execute("SET memory_limit='45GB'")
    con.execute(f"SET temp_directory='{out}/../tmp'"); con.execute("LOAD tpcds")
    t = time.time(); con.execute(f"CALL dsdgen(sf={sf})")
    n = con.execute("SELECT count(*) FROM store_sales").fetchone()[0]
    tabs = len(con.execute("SHOW TABLES").fetchall())
    assert tabs == 24 and n > 0, (tabs, n)
    con.execute("CHECKPOINT"); con.close(); os.rename(tmp, path)
    print(f"sf{sf}: {time.time()-t:.1f} s, store_sales {n:,}, {os.path.getsize(path)/2**30:.2f} GiB", flush=True)
PY
ls -lh "$OUT"
