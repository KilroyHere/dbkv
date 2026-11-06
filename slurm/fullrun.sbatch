#!/bin/bash
# Part C full run (PLAN §2g): naive vs ours, frozen system. Runs EXPORTED files from git tags, never HEAD:
#   gateway/loadgen/summarizer/gw_lib  <- tag system-frozen-v1
#   agent (run_bird.py, tools.py)      <- tag agent-frozen-v1 (220001e)
#   briefs                             <- $DBKV_DATA/frozen/system-v1 (sha256 checked against SHA256SUMS)
# Modes (MODE:RATE, run in the order given; vLLM restarts when the server config changes):
#   naive  full-schema brief, stock vLLM (FCFS), load generator direct to vLLM (no gateway)
#   ours   compact brief, priority vLLM, gateway --priority --admission $GW_K (K = 72 for compact, §2g)
#   sbatch --job-name=c_rep1 slurm/fullrun.sbatch naive:100 naive:170 naive:230 naive:300 ours:100 ours:170 ours:230 ours:300
# Cell: 1-min warm-up, 5-min measured, 3-min drain cap (unfinished counted as unfinished).
# Cost: 8 cells x ~10 min + 2 server starts -> ~1.5 h -> ~0.37 node-h; --time 2:15 caps it at 0.56.
#SBATCH --job-name=fullrun
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=02:15:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
TAG=${SYSTEM_TAG:-system-frozen-v1}
SYS=$(mktemp -d -p "$DBKV_DATA/tmp" system_frozen.XXXX); mkdir -p "$SYS/gateway"
for f in gateway.py loadgen.py summarize.py gw_lib.sh; do
  git show $TAG:harness/gateway/$f > "$SYS/gateway/$f" || { echo "cannot export $f from $TAG"; exit 1; }
done
FROZEN=$DBKV_DATA/frozen/system-v1
(cd "$FROZEN" && sha256sum -c --quiet SHA256SUMS) || { echo "frozen briefs fail sha256 check"; exit 1; }
GW_WARMUP=${GW_WARMUP:-60}; GW_MEASURE=${GW_MEASURE:-300}; GW_DRAIN=${GW_DRAIN:-180}; GW_K=${GW_K:-72}
source "$SYS/gateway/gw_lib.sh"
GWDIR=$SYS/gateway                     # gw_lib's helpers use $GWDIR: point them at the exported files
gw_export_agent                        # agent from tag agent-frozen-v1
export VLLM_SERVER_DEV_MODE=1
OUT=$DBKV_DATA/runs/fullrun/$SLURM_JOB_ID; mkdir -p "$OUT"
PORT=$(gw_free_port); URL=http://127.0.0.1:$PORT; GWPORT=$(gw_free_port); GWURL=http://127.0.0.1:$GWPORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID tag $TAG ($(git rev-parse --short $TAG)) cells: $* K=$GW_K W=$GW_WARMUP M=$GW_MEASURE drain=$GW_DRAIN"
nvidia-smi --query-gpu=name,memory.total --format=csv
trap gw_cleanup EXIT
CUR=""
for cell in "$@"; do
  mode=${cell%%:*}; rate=${cell##*:}; D="$OUT/${mode}_r${rate}"; mkdir -p "$D"
  case $mode in
    naive) cfg=fcfs;     BR=(--briefs "$FROZEN/briefs_full.jsonl" --brief-name full) ;;
    ours)  cfg=priority; BR=(--briefs "$FROZEN/briefs_compact.jsonl" --brief-name compact) ;;
    *) echo "unknown mode $mode"; continue ;;
  esac
  if [[ $cfg != $CUR ]]; then
    [[ -n $CUR ]] && gw_stop_vllm
    gw_start_vllm 0 $PORT "$OUT/server_${mode}.log" $cfg || { echo "server failed for $cell"; CUR=""; continue; }
    CUR=$cfg
  fi
  echo "$(date -Is) cell $mode rate=$rate/min"
  gw_wait_idle $URL
  curl -s -X POST $URL/reset_prefix_cache >/dev/null || true
  case $mode in
    naive) gw_loadgen "$D" $URL $rate $URL "${BR[@]}" ;;
    ours)  gw_start_gateway $GWPORT "$D/gateway.jsonl" --backends $URL --priority --admission $GW_K || continue
           gw_loadgen "$D" $GWURL $rate $URL --gateway "${BR[@]}"; gw_stop_gateway ;;
  esac
done
python "$GWDIR/summarize.py" "$OUT" > /dev/null && cat "$OUT/summary.md"
echo "$(date -Is) done"
