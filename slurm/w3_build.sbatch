#!/bin/bash
# W3 workload build (PLAN 2j Phase 0 (e)), CPU only: gold-SQL validation bank + fixed-seed streams.
#   sbatch slurm/w3_build.sbatch            # bank (121 W2 templates x tenants x 6 draws, each gold run twice) + streams
#   sbatch slurm/w3_build.sbatch streams    # streams only, from an existing bank
# 4 workers x 8 DuckDB threads, 16GB memory_limit each (the agent's caps). Estimate ~30-60 min.
#SBATCH --job-name=w3_build
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=80G
#SBATCH --time=01:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
echo "$(date -Is) $(hostname) job ${SLURM_JOB_ID:-} repo $(git rev-parse --short HEAD)"
if [[ ${1:-all} != streams ]]; then
  python -u harness/w3/build_w3.py bank --draws 6 --workers 4 --threads 8
fi
python -u harness/w3/build_w3.py streams --n 1000 --seeds 0 1 2 3 4
echo "$(date -Is) done"
