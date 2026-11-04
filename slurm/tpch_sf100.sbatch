#!/bin/bash
# Generate TPC-H SF100 as $DBKV_DATA/tpch/tpch_sf100.duckdb (~27 GB), for real long-running queries.
# dbgen runs in 10 chunks (children=10, step=0..9) so peak memory stays well under the job's ~60 GB.
# Cost: 16 physical cores = 1/8 node-hour per hour. SF10 took 11 s, so expect ~5 min -> ~0.01 node-h;
# the 1 h limit caps it at 0.125.
#SBATCH --job-name=tpch_sf100
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

OUT=$DBKV_DATA/tpch
mkdir -p "$OUT" "$DBKV_DATA/tmp"
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID: TPC-H SF100 into $OUT"

python - "$OUT" <<'EOF'
import sys, time, os, duckdb
out = sys.argv[1]
sf, children = 100, 10
path = f"{out}/tpch_sf{sf}.duckdb"; tmp = path + ".partial"
if os.path.exists(path):
    print(f"{path} exists, skipping"); sys.exit(0)
for p in (tmp, tmp + ".wal"):
    if os.path.exists(p): os.remove(p)
con = duckdb.connect(tmp)
con.execute("SET threads = 32")
con.execute("SET memory_limit = '45GB'")
con.execute(f"SET temp_directory = '{out}/../tmp'")
con.execute("LOAD tpch")
t0 = time.time()
for step in range(children):
    t = time.time()
    con.execute(f"CALL dbgen(sf={sf}, children={children}, step={step})")
    print(f"step {step}: {time.time() - t:.1f} s", flush=True)
gen = time.time() - t0
counts = {r[0]: con.execute(f"SELECT count(*) FROM {r[0]}").fetchone()[0]
          for r in con.execute("SHOW TABLES").fetchall()}
print("rows", counts, flush=True)
# Sanity: standard SF100 cardinalities (lineitem is ~600M, varies slightly).
expect = {"nation": 25, "region": 5, "supplier": 1_000_000, "customer": 15_000_000,
          "part": 20_000_000, "partsupp": 80_000_000, "orders": 150_000_000}
bad = {k: (counts.get(k), v) for k, v in expect.items() if counts.get(k) != v}
if bad or not 590_000_000 < counts.get("lineitem", 0) < 610_000_000:
    sys.exit(f"row counts off: {bad}, lineitem {counts.get('lineitem')}")
con.execute("CHECKPOINT"); con.close()
os.rename(tmp, path)   # only a complete, checked file gets the final name
print(f"sf{sf}: dbgen {gen:.1f} s, {os.path.getsize(path) / 2**30:.2f} GiB", flush=True)
EOF
ls -lh "$OUT"
echo "$(date -Is) done"
