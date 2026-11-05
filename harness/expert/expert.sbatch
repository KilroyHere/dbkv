#!/bin/bash
# Expert Stage 1.3 (docs/EXPERT.md): arms a/b/d x briefs full/oracle, 150 BIRD-dev tasks (seed 0), concurrency 8,
# one vLLM 0.33 server with the LoRA adapter loaded as model "expert".
#   sbatch harness/expert/expert.sbatch            # smoke (8 tasks, arm d full) then the 6 runs
#   EXPERT_N=5 EXPERT_RUNS="d:full" sbatch ...      # smoke only
# Needs EXPERT_ADAPTER (local adapter dir). Output: $DBKV_DATA/runs/expert/<job>/<arm>_<brief>/.
# Cost estimate: ~35 min wall -> ~0.15 node-h (cap 0.25 at --time 1:00).
#SBATCH --job-name=expert_s1
#SBATCH --account=m4999_g
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=01:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
WT=/global/cfs/cdirs/m4999/team19/ap2568/dbkv-expert
JOB=${SLURM_JOB_ID:-local}
OUT=$DBKV_DATA/runs/expert/$JOB; mkdir -p "$OUT"
PORT=$((8000 + ${SLURM_JOB_ID:-0} % 1000)); URL=http://127.0.0.1:$PORT
N=${EXPERT_N:-150}
RUNS=${EXPERT_RUNS:-"a:full b:full d:full a:oracle b:oracle d:oracle"}
: "${EXPERT_ADAPTER:?set EXPERT_ADAPTER to the local adapter dir}"
echo "$(date -Is) $(hostname) job $JOB runs: $RUNS (n=$N) adapter=$EXPERT_ADAPTER -> $OUT"
echo "worktree commit $(git -C $WT rev-parse HEAD)"; nvidia-smi --query-gpu=name,memory.total --format=csv
setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --enable-lora --max-lora-rank 16 --max-loras 1 --lora-modules expert="$EXPERT_ADAPTER" > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill -- -$SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf $URL/health >/dev/null && break; kill -0 $SERVER 2>/dev/null || break; sleep 5; done
curl -sf $URL/health >/dev/null || { echo "server failed"; tail -40 "$OUT/server.log"; exit 1; }
grep -E "GPU KV cache size" "$OUT/server.log" | tail -1
curl -s $URL/v1/models | python -c "import sys,json;print([m['id'] for m in json.load(sys.stdin)['data']])"
run() {  # arm brief n dir
  python "$WT/harness/expert/run_expert.py" --arm $1 --url $URL --bird "$DBKV_DATA/bird/dev_20240627" \
    --n $3 --seed 0 --concurrency 8 --brief $2 --out "$4" > "$4.log" 2>&1
  tail -2 "$4.log"
}
if [ -z "${EXPERT_N:-}" ]; then  # smoke: the adapter must return SQL before spending the full runs
  echo "$(date -Is) smoke d:full n=8"; run d full 8 "$OUT/smoke_d_full"
  ok=$(python -c "import json;r=[json.loads(l) for l in open('$OUT/smoke_d_full/adapter_calls.jsonl')];print(sum(1 for x in r if x.get('sql')))" 2>/dev/null || echo 0)
  echo "smoke adapter calls with SQL: $ok"; [ "$ok" -gt 0 ] || { echo "smoke failed: no adapter SQL"; exit 2; }
fi
for spec in $RUNS; do
  arm=${spec%%:*}; b=${spec##*:}
  echo "$(date -Is) run arm=$arm brief=$b"; run $arm $b $N "$OUT/${arm}_${b}"
done
echo "$(date -Is) done"
