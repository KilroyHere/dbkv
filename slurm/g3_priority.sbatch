#!/bin/bash
# Tier-2 item 2: real-vLLM test of G1's headline (program-level FCFS is what matters).
# Same node, same replayer: stock vLLM (fcfs, request arrival order) vs
# `--scheduling-policy priority` with priority = task start time (program-level FCFS; vLLM also
# preempts the lowest-priority request first). Above the limit: 8k x {24, 32}, 20k x {10, 12}.
# 1 rep each here; the G3 main sweep adds 2 more stock reps at the same points.
# Work: 2 configs x 4 points x ~6.5 min = 52 min + 2 server starts (~5-10 min each) ~ 1.1 h.
# Cost: 1 GPU shared = 1/4 node-hour per hour -> ~0.28 node-h; --time 1:30 caps it at 0.375.
#SBATCH --job-name=g3_priority
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes (job 60825603 did).
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=01:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
export VLLM_SERVER_DEV_MODE=1
OUT=$DBKV_DATA/runs/g3_priority/$SLURM_JOB_ID
mkdir -p "$OUT"
PORT=$((8000 + SLURM_JOB_ID % 1000))
POINTS=8192:24,8192:32,20480:10,20480:12
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT"

for cfg in priority fcfs; do
  [[ $cfg == priority ]] && PRIO=task_start || PRIO=none
  setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
    --enable-prefix-caching --enable-prompt-tokens-details --seed 0 --scheduling-policy $cfg \
    > "$OUT/server_$cfg.log" 2>&1 &
  SERVER=$!
  for i in $(seq 1 120); do
    curl -sf http://127.0.0.1:$PORT/health >/dev/null && break
    kill -0 $SERVER 2>/dev/null || break
    sleep 5
  done
  if curl -sf http://127.0.0.1:$PORT/health >/dev/null; then
    echo "$(date -Is) server up ($cfg)"
    timeout 3600 python "$DBKV_REPO/harness/replay.py" --url http://127.0.0.1:$PORT \
      --points $POINTS --reps 1 --warmup 60 --duration 300 --priority $PRIO --out "$OUT/$cfg"
  else
    echo "server failed to start ($cfg)"; tail -30 "$OUT/server_$cfg.log"
  fi
  kill -- -$SERVER 2>/dev/null || kill $SERVER 2>/dev/null; sleep 10
done
echo "$(date -Is) done"
