#!/bin/bash
# G3 main sweep: stock vLLM + harness/replay.py over the PLAN §3 grid, 2 reps, warmup 60 s, 300 s measured.
#
# Usage (first arg = contexts to run, comma list; RUN_NAME = stable output dir for resume):
#   one job :  sbatch --time=07:00:00 slurm/g3_sweep.sbatch 4096,8192,20480
#   two jobs:  sbatch --time=04:30:00 --job-name=g3_sweep_4k8k slurm/g3_sweep.sbatch 4096,8192
#              sbatch --time=02:20:00 --job-name=g3_sweep_20k  slurm/g3_sweep.sbatch 20480
#   Output: $SCRATCH/dbkv/runs/g3/$RUN_NAME (default RUN_NAME=main; override with --export=ALL,RUN_NAME=x).
#   Both halves of the two-job split write into the same RUN_NAME dir. Re-submitting the same command
#   skips every point whose summary.json exists (resume), so a timed-out job is simply resubmitted.
#
# Work: each run ~6.5 min (60 s warm-up + 300 s measured + ~30 s drain), server start ~10 min.
# Cost at 1 GPU shared = 1/4 node-hour per hour:
#   full (48 runs)       ~5.4 h -> ~1.35 node-h; --time 07:00 -> cap 1.75 node-h
#   4k+8k (32 runs)      ~3.6 h -> ~0.90 node-h; --time 04:30 -> cap 1.125 node-h
#   20k (16 runs)        ~1.9 h -> ~0.47 node-h; --time 02:20 -> cap 0.58 node-h
# The script stops starting new points when less than ~8 min of the time limit remain.
#SBATCH --job-name=g3_sweep
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes (job 60825603 did).
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=07:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail   # no -e: a failed point or a dead server is handled below, not fatal
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh

CTXS=${1:-${G3_CTXS:-4096,8192,20480}}
RUN_NAME=${RUN_NAME:-main}
REPS=${G3_REPS:-2}
WARMUP=${G3_WARMUP:-60}
DURATION=${G3_DURATION:-300}
ORDER_SEED=${G3_ORDER_SEED:-5470}
MAX_TRIES=${G3_MAX_TRIES:-2}          # attempts per point (a server death costs one)
MAX_RESTARTS=${G3_MAX_RESTARTS:-4}    # server restarts per job
POINT_BUDGET_S=${G3_POINT_BUDGET_S:-480}  # don't start a point with less time left than this
# per-job port: two shared-QOS jobs (e.g. the 4k8k and 20k halves) can land on one node
PORT=${G3_PORT:-$((8000 + ${SLURM_JOB_ID:-0} % 1000))}
URL=http://127.0.0.1:$PORT
OUT=${G3_OUT:-$DBKV_DATA/runs/g3/$RUN_NAME}   # G3_OUT: testing only
mkdir -p "$OUT"
JOB=${SLURM_JOB_ID:-local}
LOG() { echo "$(date -Is) $*" | tee -a "$OUT/sweep_log.txt"; }

declare -A GRID=(
  [4096]="8 16 24 32 40 48 64 96"
  [8192]="4 8 12 16 20 24 32 48"
  [20480]="2 4 6 8 10 12 16 20"
)

LOG "job $JOB on $(hostname): ctxs=$CTXS reps=$REPS warmup=$WARMUP duration=$DURATION -> $OUT"
echo "$JOB $(date -Is) ctxs=$CTXS git=$(git -C "$DBKV_REPO" rev-parse --short HEAD 2>/dev/null)" >> "$OUT/jobs.txt"
nvidia-smi > "$OUT/nvidia-smi_$JOB.txt" 2>&1
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv | tee -a "$OUT/nvidia-smi_$JOB.txt"
python -c "import torch; print('torch total_memory bytes', torch.cuda.get_device_properties(0).total_memory)" \
  | tee "$OUT/torch_mem_$JOB.txt"
[ -f "$OUT/kv_limit_predicted.txt" ] || python "$DBKV_REPO/harness/kv_limit.py" --ctx 4096 8192 20480 > "$OUT/kv_limit_predicted.txt"

# ---- plan: one line "rep ctx n" per run; each rep's points shuffled with a fixed seed ----
PLAN_POINTS=""
for c in ${CTXS//,/ }; do
  [ -n "${GRID[$c]:-}" ] || { LOG "unknown ctx $c (known: ${!GRID[*]})"; exit 2; }
  for n in ${GRID[$c]}; do PLAN_POINTS+="$c:$n "; done
done
mapfile -t PLAN < <(python - "$ORDER_SEED" "$REPS" $PLAN_POINTS <<'EOF'
import random, sys
seed, reps, pts = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
for rep in range(reps):
    p = sorted(pts, key=lambda s: tuple(map(int, s.split(":"))))
    random.Random(seed * 1000 + rep).shuffle(p)
    for s in p:
        print(rep, *s.split(":"))
EOF
)
printf '%s\n' "${PLAN[@]}" > "$OUT/order_$JOB.txt"
LOG "${#PLAN[@]} runs planned (order in order_$JOB.txt)"

# ---- server management ----
SERVER_PID=""; RESTARTS=0; NSTART=0
stop_server() {
  [ -n "$SERVER_PID" ] || return 0
  # setsid below makes the server pid its process group, so this also reaches EngineCore
  # (no pkill by name: the other half of a split sweep may share this node)
  kill -TERM -- "-$SERVER_PID" 2>/dev/null || kill -TERM "$SERVER_PID" 2>/dev/null
  for _ in $(seq 1 30); do kill -0 "$SERVER_PID" 2>/dev/null || break; sleep 2; done
  kill -KILL -- "-$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""; sleep 5
}
trap 'stop_server' EXIT
trap 'LOG "got signal, stopping"; exit 143' TERM INT

start_server() {
  NSTART=$((NSTART + 1))
  local slog="$OUT/server_${JOB}_$NSTART.log"
  LOG "starting vLLM (start #$NSTART) -> $slog"
  VLLM_SERVER_DEV_MODE=1 setsid "${G3_VLLM_BIN:-vllm}" serve "$DBKV_MODEL" --port $PORT \
    --gpu-memory-utilization 0.9 --max-model-len 32768 \
    --enable-prefix-caching --enable-prompt-tokens-details --seed 0 > "$slog" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 120); do   # up to 10 min for load + compile + CUDA graphs
    curl -sf "$URL/health" >/dev/null && break
    kill -0 "$SERVER_PID" 2>/dev/null || { LOG "server died during startup"; tail -30 "$slog"; stop_server; return 1; }
    sleep 5
  done
  curl -sf "$URL/health" >/dev/null || { LOG "server not healthy after 10 min"; tail -30 "$slog"; stop_server; return 1; }
  # progress bars use \r; split them so the grep returns only the real log lines
  tr '\r' '\n' < "$slog" | grep -E "KV cache size|Available KV|Maximum concurrency|weights took|Desired GPU memory" \
    | sed "s/^/[job $JOB start $NSTART] /" | tee -a "$OUT/kv_actual.txt"
  LOG "server up (pid $SERVER_PID)"
}

ensure_server() {
  curl -sf "$URL/health" >/dev/null && return 0
  while [ "$RESTARTS" -le "$MAX_RESTARTS" ]; do
    [ -n "$SERVER_PID" ] && { LOG "server unhealthy, restarting"; stop_server; }
    start_server && return 0
    RESTARTS=$((RESTARTS + 1))
  done
  LOG "giving up: server failed $RESTARTS times"; return 1
}

secs_left() {   # seconds until the Slurm time limit (large if not in a job)
  local l; l=$(squeue -h -j "${SLURM_JOB_ID:-0}" -o %L 2>/dev/null) || { echo 999999; return; }
  [ -n "$l" ] && [ "$l" != "INVALID" ] || { echo 999999; return; }
  local d=0; [[ $l == *-* ]] && { d=${l%%-*}; l=${l#*-}; }
  IFS=: read -r -a p <<< "$l"
  local s=0; for x in "${p[@]}"; do s=$((s * 60 + 10#$x)); done
  echo $((d * 86400 + s))
}

# ---- sweep ----
DONE=0; SKIP=0; FAIL=0
for line in "${PLAN[@]}"; do
  read -r rep c n <<< "$line"
  # replay.py with --reps 1 always names the subdir *_r0; the real rep is the rep<k> parent dir.
  pdir="$OUT/rep$rep"; sfile="$pdir/c${c}_n${n}_r0/summary.json"
  if [ -f "$sfile" ]; then SKIP=$((SKIP + 1)); continue; fi
  left=$(secs_left)
  if [ "$left" -lt "$POINT_BUDGET_S" ]; then LOG "only ${left}s left; stopping (resubmit to resume)"; break; fi
  ok=0
  for try in $(seq 1 "$MAX_TRIES"); do
    ensure_server || break 2
    LOG "run rep=$rep ctx=$c n=$n try=$try"
    # hard cap per run: warmup + duration + 10 min for drain under heavy overload
    timeout $((WARMUP + DURATION + 600)) python "$DBKV_REPO/harness/replay.py" --url "$URL" \
      --points "$c:$n" --reps 1 --seed "$rep" --warmup "$WARMUP" --duration "$DURATION" \
      --out "$pdir" >> "$OUT/replay_$JOB.log" 2>&1
    rc=$?
    if [ $rc -eq 0 ] && [ -f "$sfile" ]; then ok=1; break; fi
    LOG "run failed rc=$rc (rep=$rep ctx=$c n=$n try=$try)"; tail -5 "$OUT/replay_$JOB.log"
    # partial dir from a failed try would be overwritten by the next one; keep it for inspection
    [ -d "$pdir/c${c}_n${n}_r0" ] && mv "$pdir/c${c}_n${n}_r0" "$pdir/failed_c${c}_n${n}_r0_${JOB}_$try"
  done
  if [ $ok -eq 1 ]; then DONE=$((DONE + 1)); else FAIL=$((FAIL + 1)); fi
done
LOG "sweep end: done=$DONE skipped=$SKIP failed=$FAIL server_starts=$NSTART failed_starts=$RESTARTS"

python "$DBKV_REPO/harness/g3_summarize.py" "$OUT" || LOG "summarize failed"
remaining=0
for line in "${PLAN[@]}"; do read -r rep c n <<< "$line"; [ -f "$OUT/rep$rep/c${c}_n${n}_r0/summary.json" ] || remaining=$((remaining + 1)); done
LOG "points still missing for ctxs=$CTXS: $remaining"
