#!/bin/bash
# D2 step 5 (PLAN §2c): run brief arms on all 1,534 BIRD dev questions at concurrency 8 with the FROZEN agent.
#   sbatch --job-name=d2_A slurm/d2_arms.sbatch explore full
#   sbatch --job-name=d2_B slurm/d2_arms.sbatch compact lexical
#   sbatch --job-name=d2_C slurm/d2_arms.sbatch llm oracle
# Arms: explore (no brief) | full | compact | lexical | oracle (precomputed by harness/brief/build.py into
# $DBKV_DATA/briefs/) | llm (harness/brief/llm_select.py run here first, on this server, concurrency 8).
# Output: $DBKV_DATA/runs/d2/<job>/<arm>/{tasks,turns}.jsonl
# Cost: the 150-task check took 4.5 min, so ~46 min per 1,534-question arm; 2 arms + server ~1.8 h ->
# ~0.45 node-h per job (1/4 node-h per GPU-hour); --time 3:00 caps it at 0.75.
#SBATCH --job-name=d2_arms
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=03:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
git diff --quiet agent-frozen-v1 -- harness/agent/run_bird.py harness/agent/tools.py \
  || { echo "agent files differ from agent-frozen-v1; refusing to run"; exit 1; }
BIRD=$DBKV_DATA/bird/dev_20240627; BRIEFS=$DBKV_DATA/briefs
OUT=$DBKV_DATA/runs/d2/$SLURM_JOB_ID; mkdir -p "$OUT"
PORT=$((8000 + SLURM_JOB_ID % 1000)); URL=http://127.0.0.1:$PORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID arms: $* repo $(git rev-parse --short HEAD) -> $OUT"
nvidia-smi --query-gpu=name,memory.total --format=csv
setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 \
  --enable-auto-tool-choice --tool-call-parser hermes > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill -- -$SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf $URL/health >/dev/null && break; kill -0 $SERVER 2>/dev/null || break; sleep 5; done
curl -sf $URL/health >/dev/null || { echo "server failed"; tail -40 "$OUT/server.log"; exit 1; }
grep -E "GPU KV cache size" "$OUT/server.log" | tail -1
for arm in "$@"; do
  echo "$(date -Is) arm $arm"
  case $arm in
    explore) EXTRA=() ;;
    llm) python harness/brief/llm_select.py --url $URL --bird $BIRD --out "$OUT/briefs_llm.jsonl" --concurrency 8 --eval \
           > "$OUT/llm_select.log" 2>&1; tail -2 "$OUT/llm_select.log"
         EXTRA=(--briefs "$OUT/briefs_llm.jsonl" --brief-name llm) ;;
    *) cp "$BRIEFS/briefs_$arm.jsonl" "$OUT/"; EXTRA=(--briefs "$OUT/briefs_$arm.jsonl" --brief-name $arm) ;;
  esac
  python harness/agent/run_bird.py --url $URL --bird $BIRD --n 1534 --seed 0 --concurrency 8 "${EXTRA[@]}" \
    --out "$OUT/$arm" > "$OUT/$arm.log" 2>&1
  tail -1 "$OUT/$arm.log"
done
echo "$(date -Is) done"
