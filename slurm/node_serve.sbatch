#!/bin/bash
# Full-node template (PLAN 2j): one vLLM instance serving $DBKV_MODEL (Qwen3-32B) with TP=4 on 4 x A100-40GB,
# then the given command runs against it with VLLM_URL / VLLM_PORT / KV_POOL / OUT set.
#
#   sbatch --time=00:45:00 --job-name=<name> slurm/node_serve.sbatch <command> [args...]
#   e.g. sbatch --time=00:40:00 --job-name=n32_probe slurm/node_serve.sbatch python harness/some_probe.py --url '$VLLM_URL'
#   (the command is run with bash -c "$*", so quote $VLLM_URL etc. to expand them inside the job)
#
# ALWAYS pass --time explicitly (the header's 30 min is only a safety net). Cost: 1 node-h per hour of wall time.
# Knobs: see slurm/node_lib.sh (NODE_VLLM_EXTRA, NODE_MODEL, NODE_UTIL, ...). DRY_RUN=1 runs the checks and exits
# before vLLM (no GPU needed beyond the allocation).
# Outputs: $DBKV_DATA/runs/node/<job>/{server.log,cmd.log,kv_pool.txt}.
#SBATCH --job-name=node_serve
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=regular
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=128
#SBATCH --time=00:30:00
set -uo pipefail
# Submit from the repo root (setup/dbkv-sbatch does this and puts the log in $DBKV_DATA/logs).
source "${SLURM_SUBMIT_DIR:-$PWD}/setup/env.sh" || { echo "submit from the repo root"; exit 1; }
cd "$DBKV_REPO"
source slurm/node_lib.sh
JOB=${SLURM_JOB_ID:-local$$}
[[ $# -gt 0 ]] || { echo "usage: sbatch --time=HH:MM:SS slurm/node_serve.sbatch <command...>"; exit 1; }
OUT=$DBKV_DATA/runs/node/$JOB; mkdir -p "$OUT"; export OUT
echo "$(date -Is) $(hostname) job $JOB repo $(git rev-parse --short HEAD) model ${NODE_MODEL:-$DBKV_MODEL}"
echo "time limit: $(squeue -h -j "$JOB" -o %l 2>/dev/null)"
node_check_gpus || exit 2
[[ ${DRY_RUN:-0} == 1 ]] && { echo "DRY_RUN: exiting before vLLM"; exit 0; }

trap 'node_stop_vllm' EXIT
export VLLM_PORT=$(node_free_port); export VLLM_URL=http://127.0.0.1:$VLLM_PORT
node_start_vllm "$VLLM_PORT" "$OUT/server.log" || exit 3
export KV_POOL=$(node_kv_pool "$OUT/server.log"); echo "$KV_POOL" > "$OUT/kv_pool.txt"; echo "KV pool: $KV_POOL tokens"
bash -c "$*" 2>&1 | tee "$OUT/cmd.log"
rc=${PIPESTATUS[0]}
echo "$(date -Is) command exit $rc"
exit $rc
