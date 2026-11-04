#!/bin/bash
# G1 simulation grid (sim/g1_grid.py). v2: ~33,000 runs (5 pause mixes/scales x 24 cells x 55 policy
# variants x 5 seeds). Extra args pass through, e.g. --cost-json (G3 refit) or --pause-file (SF100 mix):
#   sbatch slurm/g1_sim.sbatch [--cost-json F] [--pause-file F]
# Quick run (1 seed, short) took 1,410 CPU-s -> full ~56,000 CPU-s ~ 20-35 min on 64 logical CPUs.
# Cost: 64 logical CPUs = 32 physical cores = 1/4 node-hour per hour -> ~0.1; 1:15 limit caps it at 0.31.
#SBATCH --job-name=g1_sim
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --time=01:15:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
OUT=$DBKV_DATA/runs/g1/$SLURM_JOB_ID
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT; args: $*"
python "$DBKV_REPO/sim/g1_grid.py" --out "$OUT" --procs 64 "$@"
echo "$(date -Is) done"
