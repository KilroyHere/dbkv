# Shared shell helpers for slurm/gw_phase2.sbatch and slurm/gw_phase3.sbatch (source after setup/env.sh).
# Knobs (env, with defaults): GW_WARMUP=120 GW_MEASURE=480 GW_DRAIN=600 GW_SEED=0 GW_K (admission limit),
# GW_VLLM_EXTRA (extra vllm serve flags, e.g. "--max-num-seqs 32").

GW_WARMUP=${GW_WARMUP:-120}; GW_MEASURE=${GW_MEASURE:-480}; GW_DRAIN=${GW_DRAIN:-600}; GW_SEED=${GW_SEED:-0}
BIRD=$DBKV_DATA/bird/dev_20240627
GWDIR=$DBKV_REPO/harness/gateway
SERVER_PIDS=()

gw_free_port() {  # a currently free TCP port on 127.0.0.1 (shared nodes: other jobs may hold fixed ports)
  python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

gw_export_agent() {  # exact export of the frozen agent (tag agent-frozen-v1) -> $AGENT_DIR
  AGENT_DIR=$(mktemp -d -p "$DBKV_DATA/tmp" frozen_agent.XXXX)
  git -C "$DBKV_REPO" show agent-frozen-v1:harness/agent/run_bird.py > "$AGENT_DIR/run_bird.py"
  git -C "$DBKV_REPO" show agent-frozen-v1:harness/agent/tools.py > "$AGENT_DIR/tools.py"
}

gw_start_vllm() {  # $1 = GPU index, $2 = port, $3 = log, $4 = "priority" or "fcfs". Same flags as d2_sweep.sbatch.
  local sched=()
  [[ $4 == priority ]] && sched=(--scheduling-policy priority)
  CUDA_VISIBLE_DEVICES=$1 setsid vllm serve "$DBKV_MODEL" --port $2 --gpu-memory-utilization 0.9 \
    --max-model-len 32768 --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics \
    --seed 0 --enable-auto-tool-choice --tool-call-parser hermes "${sched[@]}" ${GW_VLLM_EXTRA:-} > "$3" 2>&1 &
  local pid=$!
  SERVER_PIDS+=($pid)
  for i in $(seq 1 120); do curl -sf http://127.0.0.1:$2/health >/dev/null && break; kill -0 $pid 2>/dev/null || break; sleep 5; done
  curl -sf http://127.0.0.1:$2/health >/dev/null || { echo "server on GPU $1 failed"; tail -40 "$3"; return 1; }
  grep -E "GPU KV cache size" "$3" | tail -1
}

gw_cleanup() {
  [[ -n ${GW_PID:-} ]] && kill $GW_PID 2>/dev/null
  for p in "${SERVER_PIDS[@]}"; do kill -- -$p 2>/dev/null; done
  return 0
}

gw_wait_idle() {  # $@ = vLLM base URLs; wait (<= 120 s) until none has running/waiting requests
  for i in $(seq 1 60); do
    local busy=0
    for u in "$@"; do
      n=$(curl -s $u/metrics | awk '/^vllm:num_requests_(running|waiting)/ {s += $NF} END {print s+0}')
      [[ ${n%.*} -gt 0 ]] && busy=1
    done
    [[ $busy == 0 ]] && return 0
    sleep 2
  done
  echo "warning: backends still busy after 120 s"
}

gw_start_gateway() {  # $1 = port, $2 = log file, rest = gateway flags
  local port=$1 log=$2; shift 2
  python -u "$GWDIR/gateway.py" --port $port --log "$log" "$@" > "${log%.jsonl}.out" 2>&1 &
  GW_PID=$!
  for i in $(seq 1 30); do curl -sf http://127.0.0.1:$port/health >/dev/null && return 0; sleep 1; done
  echo "gateway failed to start"; cat "${log%.jsonl}.out"; return 1
}

gw_stop_gateway() {
  [[ -n ${GW_PID:-} ]] && { kill $GW_PID 2>/dev/null; wait $GW_PID 2>/dev/null; }
  GW_PID=
}

gw_loadgen() {  # $1 = cell dir, $2 = target URL, $3 = rate, $4 = metrics URLs (comma), rest = extra loadgen flags
  local d=$1 url=$2 rate=$3 murls=$4; shift 4
  timeout $(( ${GW_WARMUP%.*} + ${GW_MEASURE%.*} + ${GW_DRAIN%.*} + 600 )) \
    python -u "$GWDIR/loadgen.py" --agent-dir "$AGENT_DIR" --url $url --bird "$BIRD" --rate $rate \
      --warmup $GW_WARMUP --measure $GW_MEASURE --drain-cap $GW_DRAIN --seed $GW_SEED \
      --metrics-urls "$murls" --label "$(basename $d)" --out "$d" "$@" > "$d/loadgen.log" 2>&1
  tail -1 "$d/loadgen.log"
}

gw_stop_vllm() {  # stop every vLLM server started by this job (used to restart with another config)
  for p in "${SERVER_PIDS[@]}"; do kill -- -$p 2>/dev/null; done
  for p in "${SERVER_PIDS[@]}"; do while kill -0 $p 2>/dev/null; do sleep 1; done; done
  SERVER_PIDS=(); sleep 5
}
