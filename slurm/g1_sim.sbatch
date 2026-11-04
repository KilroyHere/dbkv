#!/bin/bash
# G1 oracle simulation grid (sim/g1_grid.py): ~6,500 runs, CPU only.
# Cost: 16 physical cores of a CPU node = 1/8 node-hour per hour; 45 min limit -> at most 0.094.
#SBATCH --job-name=g1_sim
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
OUT=$DBKV_DATA/runs/g1/$SLURM_JOB_ID
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT"
python "$DBKV_REPO/sim/g1_grid.py" --out "$OUT" --procs 32
echo "$(date -Is) done"
