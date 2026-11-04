#!/bin/bash
# Generate TPC-DS SF1 and SF10 as $DBKV_DATA/tpcds/tpcds_sf{1,10}.duckdb (DuckDB tpcds extension, dsdgen).
# Why: 99 TPC-DS query templates on top of TPC-H's 22, for G2's unseen-template test.
# Cost: 16 physical cores = 1/8 node-hour per hour. dsdgen is less parallel than dbgen; expect
# ~5-15 min -> ~0.01-0.03 node-h; the 1 h limit caps it at 0.125.
#SBATCH --job-name=tpcds_gen
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32          # 32 logical CPUs = 16 physical cores (~60 GB RAM in shared)
#SBATCH --time=01:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh

OUT=$DBKV_DATA/tpcds
mkdir -p "$OUT" "$DBKV_DATA/tmp"
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID: TPC-DS into $OUT"

python - "$OUT" <<'EOF'
import sys, time, os, duckdb
out = sys.argv[1]
for sf in (1, 10):
    path = f"{out}/tpcds_sf{sf}.duckdb"; tmp = path + ".partial"
    if os.path.exists(path):
        print(f"sf{sf}: {path} exists, skipping", flush=True); continue
    for p in (tmp, tmp + ".wal"):
        if os.path.exists(p): os.remove(p)
    con = duckdb.connect(tmp)
    con.execute("SET threads = 32")
    con.execute("SET memory_limit = '45GB'")
    con.execute(f"SET temp_directory = '{out}/../tmp'")
    con.execute("LOAD tpcds")
    t = time.time()
    con.execute(f"CALL dsdgen(sf={sf})")
    gen = time.time() - t
    counts = {r[0]: con.execute(f"SELECT count(*) FROM {r[0]}").fetchone()[0]
              for r in con.execute("SHOW TABLES").fetchall()}
    if len(counts) != 24 or not counts.get("store_sales"):
        sys.exit(f"sf{sf}: unexpected tables {counts}")
    con.execute("CHECKPOINT"); con.close()
    os.rename(tmp, path)
    print(f"sf{sf}: dsdgen {gen:.1f} s, {os.path.getsize(path) / 2**30:.2f} GiB, "
          f"store_sales {counts['store_sales']:,}, tables {len(counts)}", flush=True)
EOF
ls -lh "$OUT"
echo "$(date -Is) done"
