#!/bin/bash
# G3 smoke test: stock vLLM + synthetic replayer at a few points, incl. 20k-token sessions.
# Checks: server starts, vLLM's real KV token count (prediction 1a), replayer metrics, 20k path,
# and an above-limit 20k point (preemption path).
# Cost: 1 GPU shared = 1/4 node-hour per hour; 30 min limit -> at most 0.125 node-hours.
#SBATCH --job-name=g3_smoke
#SBATCH --account=m4999_g
#SBATCH --constraint=gpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=00:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -euo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh

OUT=$DBKV_DATA/runs/g3_smoke/$SLURM_JOB_ID
mkdir -p "$OUT"
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID -> $OUT"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python -c "import torch; print('torch total_memory bytes', torch.cuda.get_device_properties(0).total_memory)"
python "$DBKV_REPO/harness/kv_limit.py" --ctx 4096 8192 20480 | tee "$OUT/kv_limit_predicted.txt"

export VLLM_SERVER_DEV_MODE=1   # enables POST /reset_prefix_cache between points
PORT=8000
vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  --enable-prefix-caching --enable-prompt-tokens-details --seed 0 \
  > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT

for i in $(seq 1 120); do   # up to 10 min for load + compile + CUDA graphs
  curl -sf http://127.0.0.1:$PORT/health >/dev/null && break
  kill -0 $SERVER 2>/dev/null || { echo "server died"; tail -50 "$OUT/server.log"; exit 1; }
  sleep 5
done
curl -sf http://127.0.0.1:$PORT/health >/dev/null || { echo "server not healthy"; tail -50 "$OUT/server.log"; exit 1; }
echo "$(date -Is) server up"
grep -iE "KV cache (size|memory)|Available KV|Maximum concurrency|model weights took|CUDA graph" "$OUT/server.log" | tee "$OUT/kv_actual.txt"

# 4k and 8k below their predicted limits, 20k at the limit (6) and above it (10).
python "$DBKV_REPO/harness/replay.py" --url http://127.0.0.1:$PORT \
  --points 4096:8,8192:16,20480:6,20480:10 --warmup 30 --duration 120 --stagger 10 \
  --out "$OUT"
echo "$(date -Is) done"
