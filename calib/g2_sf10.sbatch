#!/bin/bash
# G2 EXPLAIN calibration, full run: TPC-H SF10 (+ TPC-DS SF10 if its file exists), then analysis.
# Each query: EXPLAIN (FORMAT JSON) x2, 1 warm-up + 3 timed runs, 60 s timeout, DuckDB capped at
# memory_limit=16GB, threads=8 (the GPU-job deployment caps, PLAN §4a).
# Time: SF1 test (interactive job 60825183) ran 932 TPC-H queries+probes in 59 s, all < 0.5 s.
# x10 for SF10 ~ 10 min; TPC-DS SF10 is unmeasured (heavier, some 60 s timeouts) -> 35 min per-db
# budget (--budget-s is per database: stop starting new queries after it), 1:30 limit.
# Cost: 32 CPUs = 16 physical cores = 1/8 node-hour per hour; --time 1:30 -> at most 0.19 node-h
# (expected ~0.05-0.1).
#SBATCH --job-name=g2_sf10
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --time=01:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
OUT=$DBKV_DATA/runs/g2/$SLURM_JOB_ID
DBS=(--db "$DBKV_DATA/tpch/tpch_sf10.duckdb")
if [ -f "$DBKV_DATA/tpcds/tpcds_sf10.duckdb" ]; then
  DBS+=(--db "$DBKV_DATA/tpcds/tpcds_sf10.duckdb")
fi
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT; dbs: ${DBS[*]}"
# 2 dbs x 35 min + stats/analysis + one last slow query (<= 4 x 60 s) fits in 1:30.
python "$DBKV_REPO/calib/g2_run.py" "${DBS[@]}" --out "$OUT" --budget-s 2100
python "$DBKV_REPO/calib/g2_analyze.py" "$OUT"
echo "$(date -Is) done"
