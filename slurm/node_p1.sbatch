#!/bin/bash
# PLAN 2j Phase 1 (and later phases): cells on one full-node vLLM server (Qwen3-32B TP=4), agent exported from a tag.
#   sbatch --time=HH:MM:SS --job-name=p1_sweep slurm/node_p1.sbatch CELL...
# Cells, run in order on one server (wait idle + prefix-cache reset between cells):
#   closed:C:N        closed loop: run_w.py, first N tasks of the stream, C concurrent agents
#   open:RATE         open loop: harness/w3/loadgen_w3.py at RATE tasks/min (P1_WARMUP / P1_MEASURE / P1_DRAIN)
#   burst             harness/w3/burst.py (64 x 2000-token prompts, 256 output tokens, 3 reps)
#   restart:on|off    restart vLLM with instrumentation on/off (NODE_STEPLOG); the server starts "on"
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
BMAP="tpch=$DBKV_DATA/w3/brief_tpch_compact.txt,tpcds=$DBKV_DATA/w3/brief_tpcds_compact.txt"
[[ $# -gt 0 ]] || { echo "usage: sbatch --time=... slurm/node_p1.sbatch CELL..."; exit 1; }
mkdir -p "$DBKV_DATA/tmp"
AGENT_DIR=$(mktemp -d -p "$DBKV_DATA/tmp" agent32.XXXX)
for f in run_w.py tools_duckdb.py; do git show "$TAG:harness/agent_duckdb/$f" > "$AGENT_DIR/$f" || { echo "export $f from $TAG failed"; exit 1; }; done
ERR=0
for f in "$STREAM" "$DBKV_DATA/w3/brief_tpch_compact.txt" "$DBKV_DATA/w3/brief_tpcds_compact.txt"; do [[ -s $f ]] || { echo "MISSING $f"; ERR=1; }; done
python -m py_compile "$AGENT_DIR/run_w.py" "$AGENT_DIR/tools_duckdb.py" harness/w3/loadgen_w3.py harness/w3/burst.py || ERR=1
NST=$(wc -l < "$STREAM")
for cell in "$@"; do
  IFS=: read -r k x y <<< "$cell"
  case $k in
    closed) [[ $x =~ ^[0-9]+$ && $y =~ ^[0-9]+$ && $y -le $NST ]] || { echo "bad cell $cell"; ERR=1; } ;;
    open) [[ $x =~ ^[0-9.]+$ ]] || { echo "bad cell $cell"; ERR=1; }
          need=$(python -c "print(int($x * ($WARM + $MEAS) / 60 * 1.3) + 20)")
          (( need <= NST )) || { echo "cell $cell may need ~$need arrivals > stream $NST"; ERR=1; } ;;
    burst) ;;
    restart) [[ $x == on || $x == off ]] || { echo "bad cell $cell"; ERR=1; } ;;
    *) echo "bad cell $cell"; ERR=1 ;;
  esac
done
echo "$(date -Is) $(hostname) job $JOB repo $(git rev-parse --short HEAD) agent $TAG ($(git rev-parse --short "$TAG^{commit}")) model ${NODE_MODEL:-$DBKV_MODEL} extra=[${NODE_VLLM_EXTRA:-}]"
echo "stream $STREAM ($NST tasks); open cells: warmup $WARM measure $MEAS drain $DRAIN; cells: $*"
[[ $ERR == 0 ]] || { echo "PLAN CHECK FAILED"; exit 1; }
node_check_gpus || exit 2
[[ ${DRY_RUN:-0} == 1 ]] && { echo "DRY_RUN ok"; exit 0; }

OUT=$DBKV_DATA/runs/p1/$JOB; mkdir -p "$OUT"
export VLLM_SERVER_DEV_MODE=1   # /reset_prefix_cache between cells
trap 'node_stop_vllm; rm -rf "$AGENT_DIR"' EXIT
SRV=0
start_server() {  # $1 = on|off
  SRV=$((SRV + 1)); PORT=$(node_free_port); URL=http://127.0.0.1:$PORT
  if [[ $1 == on ]]; then NODE_STEPLOG=1; else NODE_STEPLOG=0; fi
  node_start_vllm $PORT "$OUT/server_$SRV.log" || exit 3
  echo "server $SRV ($1): KV pool $(node_kv_pool "$OUT/server_$SRV.log")" | tee -a "$OUT/kv_pool.txt"
}
start_server on
printf "cell\tserver\tstart\tend\trc\n" > "$OUT/cells.tsv"
i=0
for cell in "$@"; do
  i=$((i + 1)); IFS=: read -r k x y <<< "$cell"
  if [[ $k == restart ]]; then node_stop_vllm; start_server $x; continue; fi
  node_wait_idle $URL
  curl -s -X POST $URL/reset_prefix_cache >/dev/null || echo "warning: prefix-cache reset failed"
  name=$(printf "%02d_%s" $i "${cell//:/_}"); d="$OUT/$name"; mkdir -p "$d"
  t0=$(date +%s.%N); echo "$(date -Is) cell $name"
  case $k in
    closed) python -u "$AGENT_DIR/run_w.py" --url $URL --stream "$STREAM" --n $y --concurrency $x --brief-map "$BMAP" \
              --out "$d" > "$d/run.log" 2>&1; rc=$?; tail -1 "$d/run.log" ;;
    open) timeout $(( WARM + MEAS + DRAIN + 900 )) python -u harness/w3/loadgen_w3.py --agent-dir "$AGENT_DIR" --url $URL \
              --stream "$STREAM" --brief-map "$BMAP" --rate $x --warmup $WARM --measure $MEAS --drain-cap $DRAIN \
              --seed $SEED --metrics-urls $URL --label "$name" --out "$d" > "$d/loadgen.log" 2>&1; rc=$?; tail -1 "$d/loadgen.log" ;;
    burst) python -u harness/w3/burst.py --url $URL --label "srv${SRV}_steplog${NODE_STEPLOG}" --out "$d/burst.json" \
              > "$d/burst.log" 2>&1; rc=$?; tail -1 "$d/burst.log" ;;
  esac
  printf "%s\t%s\t%s\t%s\t%s\n" "$name" $SRV $t0 $(date +%s.%N) $rc >> "$OUT/cells.tsv"
done
echo "$(date -Is) all cells done"
