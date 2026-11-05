#!/bin/bash
# Test 1 (D5): resume-overhead breakdown. vLLM with --enable-per-request-metrics; idle single-request
# probe (harness/d5_probe.py) then 4 loaded replay points (8k x 12, 8k x 20, 20k x 4, 20k x 8),
# 30 s warm-up + 150 s measured each. Rule: PLAN §2b Test 1.
# Work: server start ~5 min + probe ~3 min + 4 x ~3.5 min ~ 22 min. Cost: 1 GPU shared = 1/4 node-h per
# hour -> ~0.09 node-h; the 0:40 limit caps it at 0.17.
#SBATCH --job-name=d5_overhead
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=00:40:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
export VLLM_SERVER_DEV_MODE=1
OUT=$DBKV_DATA/runs/d5/$SLURM_JOB_ID; mkdir -p "$OUT"
PORT=$((8000 + SLURM_JOB_ID % 1000)); URL=http://127.0.0.1:$PORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT"; nvidia-smi --query-gpu=name,memory.total --format=csv
setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 \
  > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill -- -$SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf $URL/health >/dev/null && break; kill -0 $SERVER 2>/dev/null || break; sleep 5; done
curl -sf $URL/health >/dev/null || { echo "server failed"; tail -40 "$OUT/server.log"; exit 1; }
grep -E "GPU KV cache size" "$OUT/server.log" | tail -1
python "$DBKV_REPO/harness/d5_probe.py" --url $URL --out "$OUT/idle"
python "$DBKV_REPO/harness/replay.py" --url $URL --points 8192:12,8192:20,20480:4,20480:8 \
  --warmup 30 --duration 150 --stagger 10 --out "$OUT/loaded"
echo "$(date -Is) done"
