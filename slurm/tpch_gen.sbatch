#!/bin/bash
# Generate TPC-H SF1 and SF10 as DuckDB files in $DBKV_DATA/tpch (one file per scale factor).
# Cost: 16 physical cores of a 128-core CPU node = 1/8 node-hour per hour; 1 h limit caps it at 0.125.
# Expected ~10-15 min, so ~0.03 node-hours.
#SBATCH --job-name=tpch_gen
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32          # 32 logical CPUs = 16 physical cores (~64 GB RAM in shared)
#SBATCH --time=01:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh

OUT=$DBKV_DATA/tpch
mkdir -p "$OUT" "$DBKV_DATA/tmp"
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID: TPC-H into $OUT"

python - "$OUT" <<'EOF'
import sys, time, os, duckdb
out = sys.argv[1]
for sf in (1, 10):
    path = f"{out}/tpch_sf{sf}.duckdb"
    tmp = path + ".partial"
    for p in (tmp, tmp + ".wal"):
        if os.path.exists(p): os.remove(p)
    if os.path.exists(path):
        print(f"sf{sf}: {path} exists, skipping", flush=True); continue
    con = duckdb.connect(tmp)
    con.execute("SET threads = 32")
    con.execute("SET memory_limit = '50GB'")
    con.execute(f"SET temp_directory = '{out}/../tmp'")
    con.execute("LOAD tpch")
    t = time.time()
    con.execute(f"CALL dbgen(sf={sf})")
    gen = time.time() - t
    counts = {r[0]: con.execute(f"SELECT count(*) FROM {r[0]}").fetchone()[0]
              for r in con.execute("SHOW TABLES").fetchall()}
    con.execute("CHECKPOINT"); con.close()
    os.rename(tmp, path)   # only complete files get the final name
    size = os.path.getsize(path) / 2**30
    print(f"sf{sf}: dbgen {gen:.1f} s, {size:.2f} GiB, rows {counts}", flush=True)
EOF
ls -lh "$OUT"
echo "$(date -Is) done"
