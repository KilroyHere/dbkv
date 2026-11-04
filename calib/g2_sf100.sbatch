#!/bin/bash
# SF100 queries run ~10x SF10 (SF10 p99 0.7 s, max 14 s), so the per-db budget is 65 min (shuffled order,
# so a cut-off leaves a random subset). Cost: 1/8 node-hour per hour; ~0.15, the 1:30 limit caps it at 0.19.
# G2 on TPC-H SF100 (real long queries; also the measured pause mix for G1 v2b), then analysis.
# Each query: EXPLAIN (FORMAT JSON) x2, 1 warm-up + 3 timed runs, 60 s timeout, DuckDB capped at
# memory_limit=16GB, threads=8 (the GPU-job deployment caps, PLAN §4a).
#SBATCH --job-name=g2_sf100
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
DBS=(--db "$DBKV_DATA/tpch/tpch_sf100.duckdb")
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT; dbs: ${DBS[*]}"
# 2 dbs x 35 min + stats/analysis + one last slow query (<= 4 x 60 s) fits in 1:30.
python "$DBKV_REPO/calib/g2_run.py" "${DBS[@]}" --out "$OUT" --budget-s 3900
python "$DBKV_REPO/calib/g2_analyze.py" "$OUT"
echo "$(date -Is) done"
