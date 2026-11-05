#!/bin/bash
# D2 step 6: concurrency sweep with the FROZEN agent, prefix caching on or off (first arg), on a fixed
# 300-question subset of BIRD dev (seed 0). Each further arg is ARM:CONC, run in the given order.
#   sbatch --job-name=d2_sw_on  slurm/d2_sweep.sbatch on  explore:8 explore:32 explore:64 full:8 ...
#   sbatch --job-name=d2_sw_off slurm/d2_sweep.sbatch off explore:8 ...
# Brief placement: the frozen agent puts the fixed instructions first, then the brief, then the question,
# so all agents on the same database share an identical prefix (instructions + per-DB brief) for the
# per-database arms (full, compact). Narrowed briefs (lexical, llm, oracle) are per question.
# A sampler records vllm:kv_cache_usage_perc, num_requests_running/waiting and the counters for
# prefix-cache queries/hits and preemptions every 2 s into <arm>_c<conc>/metrics.jsonl.
# Cost: ~5-10 min per cell; 12 cells per job ~1.5-2 h -> ~0.4-0.5 node-h; --time 3:00 caps at 0.75.
#SBATCH --job-name=d2_sweep
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
PC=$1; shift
[[ $PC == on ]] && PCFLAG=--enable-prefix-caching || PCFLAG=--no-enable-prefix-caching
BIRD=$DBKV_DATA/bird/dev_20240627; BRIEFS=${D2_BRIEFS:-$DBKV_DATA/briefs}; N=${D2_N:-300}
OUT=$DBKV_DATA/runs/d2sweep/$SLURM_JOB_ID; mkdir -p "$OUT"
PORT=$((8000 + SLURM_JOB_ID % 1000)); URL=http://127.0.0.1:$PORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID prefix-caching=$PC cells: $* repo $(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,memory.total --format=csv
setsid vllm serve "$DBKV_MODEL" --port $PORT --gpu-memory-utilization 0.9 --max-model-len 32768 \
  $PCFLAG --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 \
  --enable-auto-tool-choice --tool-call-parser hermes > "$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill -- -$SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do curl -sf $URL/health >/dev/null && break; kill -0 $SERVER 2>/dev/null || break; sleep 5; done
curl -sf $URL/health >/dev/null || { echo "server failed"; tail -40 "$OUT/server.log"; exit 1; }
grep -E "GPU KV cache size" "$OUT/server.log" | tail -1
sample() {  # $1 = output file; samples /metrics every 2 s until killed
  while true; do
    curl -s $URL/metrics | python -c '
import sys, json, time
keep = ("vllm:kv_cache_usage_perc", "vllm:num_requests_running", "vllm:num_requests_waiting",
        "vllm:prefix_cache_queries", "vllm:prefix_cache_hits", "vllm:num_preemptions")
d = {"t": time.time()}
for line in sys.stdin:
    if line.startswith("#") or not line.strip(): continue
    name = line.split("{")[0].split(" ")[0]
    for k in keep:
        if name in (k, k + "_total"): d[k] = d.get(k, 0.0) + float(line.rsplit(" ", 1)[1])
print(json.dumps(d))' >> "$1"
    sleep 2
  done
}
for cell in "$@"; do
  arm=${cell%%:*}; c=${cell##*:}; D="$OUT/${arm}_c$c"; mkdir -p "$D"
  case $arm in
    explore) EXTRA=() ;;
    *) EXTRA=(--briefs "$BRIEFS/briefs_$arm.jsonl" --brief-name $arm) ;;
  esac
  echo "$(date -Is) cell $arm c=$c"
  sample "$D/metrics.jsonl" & SP=$!
  python harness/agent/run_bird.py --url $URL --bird $BIRD --n $N --seed 0 --concurrency $c "${EXTRA[@]}" \
    --out "$D" > "$D.log" 2>&1
  kill $SP 2>/dev/null; tail -1 "$D.log"
done
echo "$(date -Is) done"
