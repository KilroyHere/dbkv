# Shell helpers for full-node GPU jobs (PLAN 2j): one vLLM instance with tensor parallel 4 on 4 x A100-40GB.
# Source after setup/env.sh. Used by slurm/node_*.sbatch.
#
# Knobs (env):
#   NODE_TP=4                     tensor-parallel size
#   NODE_UTIL=0.9                 --gpu-memory-utilization
#   NODE_MAXLEN=32768             --max-model-len
#   NODE_VLLM_EXTRA=""            extra vllm serve flags for an option switch, e.g.
#                                 "--scheduling-policy priority" (A(a)), '--speculative-config {"method":"suffix"}' (A(b)),
#                                 "--kv-cache-dtype fp8" (A(d)). Word-split: no spaces inside one flag value.
#   NODE_MODEL=$DBKV_MODEL        model (A(c) passes a W8A8 checkpoint path here)
#   NODE_START_TIMEOUT=1500       seconds to wait for /health (32B TP=4 load + compile + CUDA graphs)
# Cost: a full node is charged 1 node-h per hour of wall time, idle server start-up included.

NODE_TP=${NODE_TP:-4}; NODE_UTIL=${NODE_UTIL:-0.9}; NODE_MAXLEN=${NODE_MAXLEN:-32768}
NODE_START_TIMEOUT=${NODE_START_TIMEOUT:-1500}
# Phase 1 instrumentation, on by default in every 2j job (NODE_STEPLOG=0 turns it off, e.g. for the overhead control):
# per-step engine log via the dbkv_steplog plugin (harness/vllm_steplog) -> $DBKV_STEPLOG, iteration details,
# sampled KV eviction events. The plugin is inert when DBKV_STEPLOG is unset.
NODE_STEPLOG=${NODE_STEPLOG:-1}
NODE_SERVER_PID=

node_free_port() {
  python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

node_check_gpus() {  # abort unless this node has exactly NODE_TP A100-SXM4-40GB GPUs visible (80GB invalidates KV results)
  local q; q=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null) || { echo "nvidia-smi failed"; return 1; }
  echo "$q" | sed 's/^/  gpu: /'
  local n bad
  n=$(echo "$q" | grep -c .)
  bad=$(echo "$q" | awk -F', ' '$2 > 45000 || $2 < 39000 || $1 !~ /A100-SXM4/' | grep -c .)
  [[ $n -ge $NODE_TP && $bad -eq 0 ]] || { echo "NODE CHECK FAILED: need $NODE_TP x 40GB GPUs, got $n (non-40GB: $bad)"; return 1; }
  nvidia-smi topo -m 2>/dev/null | head -6
}

node_start_vllm() {  # $1 = port, $2 = server log. Flags = the 2j base set + NODE_VLLM_EXTRA.
  local port=$1 log=$2
  local model=${NODE_MODEL:-$DBKV_MODEL}
  echo "$(date -Is) vllm serve $model steplog=$NODE_STEPLOG TP=$NODE_TP util=$NODE_UTIL maxlen=$NODE_MAXLEN extra=[${NODE_VLLM_EXTRA:-}]"
  local obs=()
  if [[ $NODE_STEPLOG == 1 ]]; then
    obs=(--enable-logging-iteration-details --kv-cache-metrics)
    export DBKV_STEPLOG=${log%.log}_steps.jsonl   # one step log per server start
    echo "steplog: $DBKV_STEPLOG"
  else
    unset DBKV_STEPLOG
  fi
  setsid vllm serve "$model" --port "$port" --tensor-parallel-size "$NODE_TP" \
    --gpu-memory-utilization "$NODE_UTIL" --max-model-len "$NODE_MAXLEN" \
    --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics \
    --seed 0 --enable-auto-tool-choice --tool-call-parser hermes "${obs[@]}" ${NODE_VLLM_EXTRA:-} > "$log" 2>&1 &
  NODE_SERVER_PID=$!
  local t0=$SECONDS
  while (( SECONDS - t0 < NODE_START_TIMEOUT )); do
    curl -sf "http://127.0.0.1:$port/health" >/dev/null && break
    kill -0 $NODE_SERVER_PID 2>/dev/null || break
    sleep 5
  done
  curl -sf "http://127.0.0.1:$port/health" >/dev/null || { echo "vLLM failed to start ($((SECONDS - t0)) s)"; tail -60 "$log"; return 1; }
  echo "vLLM up after $((SECONDS - t0)) s"
  grep -E "GPU KV cache size|Available KV cache memory|Maximum concurrency" "$log" | tail -3
  return 0
}

node_kv_pool() {  # $1 = server log -> prints the KV pool in tokens (vLLM's own number)
  grep -oE "GPU KV cache size: [0-9,]+ tokens" "$1" | tail -1 | grep -oE "[0-9,]+" | tr -d ,
}

node_wait_idle() {  # $1 = base URL; wait (<= 180 s) until no running/waiting requests
  local u=$1 n
  for i in $(seq 1 90); do
    n=$(curl -s "$u/metrics" | awk '/^vllm:num_requests_(running|waiting)/ {s += $NF} END {print s+0}')
    [[ ${n%.*} -eq 0 ]] && return 0
    sleep 2
  done
  echo "warning: server still busy after 180 s"
}

node_stop_vllm() {
  [[ -n $NODE_SERVER_PID ]] || return 0
  kill -- -"$NODE_SERVER_PID" 2>/dev/null
  for i in $(seq 1 60); do kill -0 "$NODE_SERVER_PID" 2>/dev/null || break; sleep 1; done
  kill -9 -- -"$NODE_SERVER_PID" 2>/dev/null
  NODE_SERVER_PID=; sleep 5
}
