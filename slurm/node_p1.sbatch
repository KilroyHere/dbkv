#!/bin/bash
# PLAN 2j Phase 1 (and later phases): cells on one full-node vLLM server (Qwen3-32B TP=4), agent exported from a tag.
#   sbatch --time=HH:MM:SS --job-name=p1_sweep slurm/node_p1.sbatch CELL...
# Cells, run in order on one server (wait idle + prefix-cache reset between cells):
#   closed:C:N        closed loop: run_w.py, first N tasks of the stream, C concurrent agents
#   open:RATE         open loop: harness/w3/loadgen_w3.py at RATE tasks/min (P1_WARMUP / P1_MEASURE / P1_DRAIN)
#   openx:RATE:SET    open loop direct to vLLM with a named load-generator set (PLAN 2j-D):
#                       dbdef  --db-sched off (DuckDB default: plain thread pool of 32)
#                       dbx    --db-sched explain (option D: EXPLAIN classes, short first, caps 3 long / 8 heavy,
#                              task-start order, starvation 30 s, deadline 60 s)
#                       dbobs  --db-sched observe (FIFO + class log)
#   burst             harness/w3/burst.py (64 x 2000-token prompts, 256 output tokens, 3 reps)
#   restart:on|off    restart vLLM with instrumentation on/off (NODE_STEPLOG); the server starts "on"
#   server:CFG        restart vLLM with config CFG = "+"-joined switches (Phase 2 arms; instrumentation stays on):
#                       fcfs (stock), prio (--scheduling-policy priority), suffix (suffix decoding),
#                       fp8 (--kv-cache-dtype fp8), w8a8 (model = $W8A8_MODEL),
#                       suffixN (suffix with num_speculative_tokens=N, e.g. suffix8; plain "suffix" = vLLM default 24),
#                       js (option C: DBKV_JOINTSPEC=1 with JS_BUDGET (1024), JS_THETA (0.5), JS_MIN (0.05); decision
#                       log $OUT/jointspec_srv<k>_{pid}.jsonl),
#                       te (option E: DBKV_TASKEVICT=1, mode $TE_MODE (full), TTL 300 s, task_end listener on $TE_PORT
#                       (8899), stats log $OUT/taskevict_srv<k>.jsonl). e.g. server:prio+suffix+fp8, server:fcfs+suffix+js
#                     If the first cell is server:CFG, the job starts with that config (no extra start).
#   gw:RATE:K|auto    open loop through harness/gateway/gateway.py: admission K whole tasks + task-start priority;
#                     auto = floor(KV pool of the running server / TASK_KV), TASK_KV default 2260 (PLAN 2j-A)
#   gwx:RATE:SET      open loop through the gateway with a named flag set (PLAN 2j-B), K = auto as above:
#                       tl<N>  static turn limit N (no admission; priority only if the server has "prio")
#                       gp     B: admission K + goodput priority (table $GP_TABLE) + forced final answer when tasks
#                              wait for admission (--force-final 0 --force-frac 0.1 --force-min-turn 2)
#                       gpp    B without forcing: admission K + goodput priority
#                       pt     pass-through (no policy; same proxy overhead as the te arm)
#                       te     pass-through + option E task tags and task-end signals to $TE_PORT
#                     (priority is injected only if the running server has "prio"); --idle-timeout $GW_IDLE (600)
# Knobs: P1_STREAM (default $DBKV_DATA/w3/streams/w3_mix_s${P1_SEED}.jsonl), P1_SEED (0), P1_WARMUP (60),
#   P1_MEASURE (300), P1_DRAIN (180), AGENT_TAG (agent-32b-v1), NODE_VLLM_EXTRA (option switches), DRY_RUN=1.
# Outputs: $DBKV_DATA/runs/p1/<job>/<NN_cell>/..., server_<k>.log + server_<k>_steps.jsonl, cells.tsv
#   (cell, server, start/end epoch), kv_pool.txt.
#SBATCH --job-name=node_p1
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=regular
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=128
#SBATCH --time=00:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
source slurm/node_lib.sh
JOB=${SLURM_JOB_ID:-local$$}
SEED=${P1_SEED:-0}
STREAM=${P1_STREAM:-$DBKV_DATA/w3/streams/w3_mix_s${SEED}.jsonl}
WARM=${P1_WARMUP:-60}; MEAS=${P1_MEASURE:-300}; DRAIN=${P1_DRAIN:-180}
TAG=${AGENT_TAG:-agent-32b-v1}
GW_IDLE=${GW_IDLE:-600}
W8A8_MODEL=${W8A8_MODEL:-RedHatAI/Qwen3-32B-quantized.w8a8}
GP_TABLE=${GP_TABLE:-$DBKV_DATA/goodput/b_train_s12.json}
BMAP="tpch=$DBKV_DATA/w3/brief_tpch_compact.txt,tpcds=$DBKV_DATA/w3/brief_tpcds_compact.txt"
[[ $# -gt 0 ]] || { echo "usage: sbatch --time=... slurm/node_p1.sbatch CELL..."; exit 1; }
mkdir -p "$DBKV_DATA/tmp"
AGENT_DIR=$(mktemp -d -p "$DBKV_DATA/tmp" agent32.XXXX)
for f in run_w.py tools_duckdb.py; do git show "$TAG:harness/agent_duckdb/$f" > "$AGENT_DIR/$f" || { echo "export $f from $TAG failed"; exit 1; }; done
# Snapshot the harness (gateway, load generator, burst) at job start, so repo changes during the job cannot leak in.
HSNAP=$(mktemp -d -p "$DBKV_DATA/tmp" harness.XXXX)
mkdir -p "$HSNAP/harness/gateway" "$HSNAP/harness/w3" "$HSNAP/calib"   # same layout as the repo (dbsched imports ../../calib)
cp harness/gateway/*.py "$HSNAP/harness/gateway/" && cp harness/w3/*.py harness/w3/*.json "$HSNAP/harness/w3/" \
  && cp calib/*.py "$HSNAP/calib/" || { echo "harness snapshot failed"; exit 1; }
TASK_KV=${TASK_KV:-2260}
ERR=0
for f in "$STREAM" "$DBKV_DATA/w3/brief_tpch_compact.txt" "$DBKV_DATA/w3/brief_tpcds_compact.txt"; do [[ -s $f ]] || { echo "MISSING $f"; ERR=1; }; done
python -m py_compile "$AGENT_DIR/run_w.py" "$AGENT_DIR/tools_duckdb.py" "$HSNAP/harness/w3/loadgen_w3.py" "$HSNAP/harness/w3/burst.py" "$HSNAP/harness/gateway/gateway.py" || ERR=1
NST=$(wc -l < "$STREAM")
for cell in "$@"; do
  IFS=: read -r k x y <<< "$cell"
  case $k in
    closed) [[ $x =~ ^[0-9]+$ && $y =~ ^[0-9]+$ && $y -le $NST ]] || { echo "bad cell $cell"; ERR=1; } ;;
    gw) [[ $x =~ ^[0-9.]+$ && ( $y =~ ^[0-9]+$ || $y == auto ) ]] || { echo "bad cell $cell"; ERR=1; }
          need=$(python -c "print(int($x * ($WARM + $MEAS) / 60 * 1.3) + 20)")
          (( need <= NST )) || { echo "cell $cell may need ~$need arrivals > stream $NST"; ERR=1; } ;;
    openx) [[ $x =~ ^[0-9.]+$ && $y =~ ^(dbdef|dbx|dbobs)$ ]] || { echo "bad cell $cell"; ERR=1; } ;;
    gwx) [[ $x =~ ^[0-9.]+$ && $y =~ ^(tl[0-9]+|gp|gpp|pt|te)$ ]] || { echo "bad cell $cell"; ERR=1; }
          [[ $y =~ ^gp && ! -s $GP_TABLE ]] && { echo "MISSING goodput table $GP_TABLE"; ERR=1; } ;;
    server) for sw in ${x//+/ }; do [[ $sw =~ ^(fcfs|prio|suffix|suffix[0-9]+|fp8|w8a8|js|te)$ ]] || { echo "bad switch $sw in $cell"; ERR=1; }; done ;;
    open) [[ $x =~ ^[0-9.]+$ ]] || { echo "bad cell $cell"; ERR=1; }
          need=$(python -c "print(int($x * ($WARM + $MEAS) / 60 * 1.3) + 20)")
          (( need <= NST )) || { echo "cell $cell may need ~$need arrivals > stream $NST"; ERR=1; } ;;
    burst) ;;
    restart) [[ $x == on || $x == off ]] || { echo "bad cell $cell"; ERR=1; } ;;
    *) echo "bad cell $cell"; ERR=1 ;;
  esac
done
echo "$(date -Is) $(hostname) job $JOB repo $(git rev-parse --short HEAD)$( [[ -n $(git status --porcelain harness slurm) ]] && echo ' +uncommitted') harness snapshot $HSNAP agent $TAG ($(git rev-parse --short "$TAG^{commit}")) model ${NODE_MODEL:-$DBKV_MODEL} extra=[${NODE_VLLM_EXTRA:-}]"
echo "stream $STREAM ($NST tasks); open cells: warmup $WARM measure $MEAS drain $DRAIN; cells: $*"
[[ $ERR == 0 ]] || { echo "PLAN CHECK FAILED"; rm -rf "$AGENT_DIR" "$HSNAP"; exit 1; }
node_check_gpus || { rm -rf "$AGENT_DIR" "$HSNAP"; exit 2; }
[[ ${DRY_RUN:-0} == 1 ]] && { echo "DRY_RUN ok"; rm -rf "$AGENT_DIR" "$HSNAP"; exit 0; }

OUT=$DBKV_DATA/runs/p1/$JOB; mkdir -p "$OUT"
export VLLM_SERVER_DEV_MODE=1   # /reset_prefix_cache between cells
GW_PID=
trap 'node_stop_vllm; [[ -n $GW_PID ]] && kill $GW_PID 2>/dev/null; rm -rf "$AGENT_DIR" "$HSNAP"' EXIT
SRV=0; CFG=fcfs; LOGON=on
cfg_flags() {  # $1 = CFG -> sets NODE_VLLM_EXTRA and NODE_MODEL
  local extra=() sw
  NODE_MODEL=$DBKV_MODEL
  unset DBKV_JOINTSPEC DBKV_JOINTSPEC_BUDGET DBKV_JOINTSPEC_THETA DBKV_JOINTSPEC_MIN_VALUE DBKV_JOINTSPEC_LOG
  unset DBKV_TASKEVICT DBKV_TASKEVICT_MODE DBKV_TASKEVICT_TTL DBKV_TASKEVICT_PORT DBKV_TASKEVICT_LOG
  for sw in ${1//+/ }; do
    case $sw in
      suffix[0-9]*) extra+=("--speculative-config {\"method\":\"suffix\",\"num_speculative_tokens\":${sw#suffix}}") ;;
      te) export DBKV_TASKEVICT=1 DBKV_TASKEVICT_MODE=${TE_MODE:-full} DBKV_TASKEVICT_TTL=300 \
                 DBKV_TASKEVICT_PORT=${TE_PORT:-8899} DBKV_TASKEVICT_LOG="$OUT/taskevict_srv${SRV}.jsonl" ;;
      js) export DBKV_JOINTSPEC=1 DBKV_JOINTSPEC_BUDGET=${JS_BUDGET:-1024} DBKV_JOINTSPEC_THETA=${JS_THETA:-0.5} \
                 DBKV_JOINTSPEC_MIN_VALUE=${JS_MIN:-0.05} DBKV_JOINTSPEC_LOG="$OUT/jointspec_srv${SRV}_{pid}.jsonl" ;;  # cfg_flags runs after SRV is incremented
      prio) extra+=(--scheduling-policy priority) ;;
      suffix) extra+=('--speculative-config {"method":"suffix"}') ;;
      fp8) extra+=(--kv-cache-dtype fp8) ;;
      w8a8) NODE_MODEL=$W8A8_MODEL ;;
    esac
  done
  NODE_VLLM_EXTRA="${extra[*]}"
}
start_server() {  # $1 = on|off (instrumentation), uses $CFG
  SRV=$((SRV + 1)); PORT=$(node_free_port); URL=http://127.0.0.1:$PORT
  if [[ $1 == on ]]; then NODE_STEPLOG=1; else NODE_STEPLOG=0; fi
  cfg_flags "$CFG"
  node_start_vllm $PORT "$OUT/server_$SRV.log" || exit 3
  echo "server $SRV ($1, $CFG): KV pool $(node_kv_pool "$OUT/server_$SRV.log")" | tee -a "$OUT/kv_pool.txt"
  grep -hE "dbkv_jointspec: (ACTIVE|inactive)|dbkv_taskevict|task_end listener|max_num_scheduled_tokens" "$OUT/server_$SRV.log" | tail -4
  printf "%s\t%s\t%s\n" $SRV "$CFG" "$1" >> "$OUT/servers.tsv"
}
printf "server\tcfg\tinstrumentation\n" > "$OUT/servers.tsv"
first=${1%%:*}
if [[ $first == server ]]; then CFG=${1#server:}; shift; fi
start_server on
printf "cell\tserver\tstart\tend\trc\n" > "$OUT/cells.tsv"
i=0
for cell in "$@"; do
  i=$((i + 1)); IFS=: read -r k x y <<< "$cell"
  if [[ $k == restart ]]; then node_stop_vllm; LOGON=$x; start_server $x; continue; fi
  if [[ $k == server ]]; then node_stop_vllm; CFG=$x; start_server $LOGON; continue; fi
  node_wait_idle $URL
  curl -s -X POST $URL/reset_prefix_cache >/dev/null || echo "warning: prefix-cache reset failed"
  name=$(printf "%02d_%s" $i "${cell//:/_}"); d="$OUT/$name"; mkdir -p "$d"
  t0=$(date +%s.%N); echo "$(date -Is) cell $name"
  case $k in
    closed) python -u "$AGENT_DIR/run_w.py" --url $URL --stream "$STREAM" --n $y --concurrency $x --brief-map "$BMAP" \
              --out "$d" > "$d/run.log" 2>&1; rc=$?; tail -1 "$d/run.log" ;;
    openx) case $y in
          dbdef) lgx=(--db-sched off) ;;
          dbx)   lgx=(--db-sched explain --db-sched-long-cap 3 --db-sched-heavy-cap 8 --db-sched-order taskstart
                      --db-sched-starve-s 30 --db-sched-deadline-s 60) ;;
          dbobs) lgx=(--db-sched observe) ;;
        esac
        echo "  loadgen ${lgx[*]}"
        timeout $(( WARM + MEAS + DRAIN + 900 )) python -u "$HSNAP/harness/w3/loadgen_w3.py" --agent-dir "$AGENT_DIR" --url $URL \
              --stream "$STREAM" --brief-map "$BMAP" --rate $x --warmup $WARM --measure $MEAS --drain-cap $DRAIN \
              --seed $SEED --metrics-urls $URL --label "$name" --out "$d" "${lgx[@]}" > "$d/loadgen.log" 2>&1; rc=$?
        tail -1 "$d/loadgen.log" ;;
    open) timeout $(( WARM + MEAS + DRAIN + 900 )) python -u "$HSNAP/harness/w3/loadgen_w3.py" --agent-dir "$AGENT_DIR" --url $URL \
              --stream "$STREAM" --brief-map "$BMAP" --rate $x --warmup $WARM --measure $MEAS --drain-cap $DRAIN \
              --seed $SEED --metrics-urls $URL --label "$name" --out "$d" > "$d/loadgen.log" 2>&1; rc=$?; tail -1 "$d/loadgen.log" ;;
    gw|gwx) GWP=$(node_free_port); gwprio=(); [[ "+$CFG+" == *+prio+* ]] && gwprio=(--priority)
        KA=$(( $(node_kv_pool "$OUT/server_$SRV.log") / TASK_KV ))
        if [[ $k == gw ]]; then K=$y; [[ $K == auto ]] && K=$KA; gwargs=(--admission $K "${gwprio[@]}")
        else case $y in
          tl*) gwargs=(--turn-limit ${y#tl} "${gwprio[@]}") ;;
          gp)  gwargs=(--admission $KA --goodput "$GP_TABLE" --force-final 0 --force-frac 0.1 --force-min-turn 2) ;;
          gpp) gwargs=(--admission $KA --goodput "$GP_TABLE") ;;
          pt)  gwargs=("${gwprio[@]}") ;;
          te)  gwargs=("${gwprio[@]}" --taskevict http --taskevict-endpoints http://127.0.0.1:${TE_PORT:-8899}/task_end) ;;
        esac; fi
        echo "  gateway ${gwargs[*]}"
        python -u "$HSNAP/harness/gateway/gateway.py" --port $GWP --backends $URL "${gwargs[@]}" \
          --idle-timeout $GW_IDLE --log "$d/gateway.jsonl" > "$d/gateway.out" 2>&1 & GW_PID=$!
        for _ in $(seq 1 30); do curl -sf http://127.0.0.1:$GWP/health >/dev/null && break; sleep 1; done
        timeout $(( WARM + MEAS + DRAIN + 900 )) python -u "$HSNAP/harness/w3/loadgen_w3.py" --agent-dir "$AGENT_DIR" \
              --url http://127.0.0.1:$GWP --gateway --stream "$STREAM" --brief-map "$BMAP" --rate $x --warmup $WARM \
              --measure $MEAS --drain-cap $DRAIN --seed $SEED --metrics-urls $URL --label "$name" --out "$d" \
              > "$d/loadgen.log" 2>&1; rc=$?; tail -1 "$d/loadgen.log"
        kill $GW_PID 2>/dev/null; wait $GW_PID 2>/dev/null; GW_PID= ;;
    burst) python -u "$HSNAP/harness/w3/burst.py" --url $URL --label "srv${SRV}_steplog${NODE_STEPLOG}" --out "$d/burst.json" \
              > "$d/burst.log" 2>&1; rc=$?; tail -1 "$d/burst.log" ;;
  esac
  printf "%s\t%s\t%s\t%s\t%s\n" "$name" $SRV $t0 $(date +%s.%N) $rc >> "$OUT/cells.tsv"
done
echo "$(date -Is) all cells done"
