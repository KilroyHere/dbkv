#!/bin/bash
# Tests 2 and 3 (PLAN §2b): ReAct SQL agent (harness/agent/run_bird.py) on BIRD dev, Qwen3-8B.
#   Test 2:  sbatch --time=03:30:00 --job-name=t2_agent slurm/agent_bird.sbatch 1:none 8:none
#   Test 3:  sbatch --time=01:30:00 --job-name=t3_brief slurm/agent_bird.sbatch 8:full 8:oracle
# Each arg CONC:BRIEF is one 150-task run (seed 0) against one vLLM server; output under
# $DBKV_DATA/runs/agent/<job>/c<CONC>_<BRIEF>/. AGENT_N overrides the task count (smoke tests).
# Cost: 1 GPU shared = 1/4 node-hour per hour. Smoke (16 tasks, c=8) took 8 s, so a 150-task run is ~2-15 min;
# Test 2 ~0.5 h incl. server start -> ~0.12 (cap 0.25 at --time 1:00); Test 3 similar.
#SBATCH --job-name=agent_bird
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=03:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
JOB=${SLURM_JOB_ID:-local}
OUT=$DBKV_DATA/runs/agent/$JOB; mkdir -p "$OUT"
PORT=$((8000 + ${SLURM_JOB_ID:-0} % 1000)); URL=http://127.0.0.1:$PORT
N=${AGENT_N:-150}
echo "$(date -Is) $(hostname) job $JOB runs: $* (n=$N) -> $OUT"; nvidia-smi --query-gpu=name,memory.total --format=csv
setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 \
  --enable-auto-tool-choice --tool-call-parser hermes > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill -- -$SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf $URL/health >/dev/null && break; kill -0 $SERVER 2>/dev/null || break; sleep 5; done
curl -sf $URL/health >/dev/null || { echo "server failed"; tail -40 "$OUT/server.log"; exit 1; }
grep -E "GPU KV cache size" "$OUT/server.log" | tail -1
for spec in "$@"; do
  c=${spec%%:*}; b=${spec##*:}
  echo "$(date -Is) run concurrency=$c brief=$b"
  python "$DBKV_REPO/harness/agent/run_bird.py" --url $URL --bird "$DBKV_DATA/bird/dev_20240627" \
    --n $N --seed 0 --concurrency $c --brief $b --out "$OUT/c${c}_${b}" > "$OUT/c${c}_${b}.log" 2>&1
  tail -1 "$OUT/c${c}_${b}.log"
done
echo "$(date -Is) done"
