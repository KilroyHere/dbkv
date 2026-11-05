#!/bin/bash
# Stage A (Nov 5): brief-aware prompt quick check. 150 BIRD dev questions (seed 0), concurrency 8, lexical briefs.
#   (1) frozen agent (exported from tag agent-frozen-v1), lexical briefs
#   (2) brief-aware prompt (harness/agent @ HEAD, --prompt brief_aware), lexical briefs
#   (3) brief-aware prompt, lexical briefs + short BIRD column descriptions (briefs_lexical_desc)
# Gate (harness/brief/stage_metrics.py --gate): describe-on-brief <= 0.3/task, no-SQL < 5%, acc >= (1) - 3 points.
# Cost: 3 x ~2-4 min + server start ~5 min -> ~0.06 node-h at 1/4 node-h per GPU-hour; --time 0:40 caps at 0.17.
#SBATCH --job-name=stage_a
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
cd "$DBKV_REPO"
BIRD=$DBKV_DATA/bird/dev_20240627; BR=$DBKV_DATA/briefs
OUT=$DBKV_DATA/runs/stage_a/$SLURM_JOB_ID; mkdir -p "$OUT/frozen_agent"
git show agent-frozen-v1:harness/agent/run_bird.py > "$OUT/frozen_agent/run_bird.py"
git show agent-frozen-v1:harness/agent/tools.py > "$OUT/frozen_agent/tools.py"
grep -q 'brief_aware' harness/agent/run_bird.py || { echo "HEAD agent has no --prompt brief_aware"; exit 1; }
PORT=$((8000 + SLURM_JOB_ID % 1000)); URL=http://127.0.0.1:$PORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID repo $(git rev-parse --short HEAD)"; nvidia-smi --query-gpu=name,memory.total --format=csv
setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 \
  --enable-auto-tool-choice --tool-call-parser hermes > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill -- -$SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf $URL/health >/dev/null && break; kill -0 $SERVER 2>/dev/null || break; sleep 5; done
curl -sf $URL/health >/dev/null || { echo "server failed"; tail -40 "$OUT/server.log"; exit 1; }
COMMON=(--url $URL --bird $BIRD --n 150 --seed 0 --concurrency 8)
python "$OUT/frozen_agent/run_bird.py" "${COMMON[@]}" --briefs $BR/briefs_lexical.jsonl --brief-name lexical --out "$OUT/a1_frozen" > "$OUT/a1.log" 2>&1; tail -1 "$OUT/a1.log"
python harness/agent/run_bird.py "${COMMON[@]}" --prompt brief_aware --briefs $BR/briefs_lexical.jsonl --brief-name lexical --out "$OUT/a2_aware" > "$OUT/a2.log" 2>&1; tail -1 "$OUT/a2.log"
python harness/agent/run_bird.py "${COMMON[@]}" --prompt brief_aware --briefs $BR/briefs_lexical_desc.jsonl --brief-name lexical_desc --out "$OUT/a3_aware_desc" > "$OUT/a3.log" 2>&1; tail -1 "$OUT/a3.log"
python harness/brief/stage_metrics.py --title "Stage A: brief-aware prompt (150 questions, concurrency 8, lexical briefs)" \
  --run "(1) frozen=$OUT/a1_frozen@$BR/briefs_lexical.jsonl" --run "(2) aware=$OUT/a2_aware@$BR/briefs_lexical.jsonl" \
  --run "(3) aware+desc=$OUT/a3_aware_desc@$BR/briefs_lexical_desc.jsonl" --ref "(1) frozen" --gate --out "$OUT/stage_a.md"
echo "$(date -Is) done"
