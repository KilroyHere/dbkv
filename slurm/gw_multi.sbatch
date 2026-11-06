#!/bin/bash
# Same-job comparisons across vLLM server configs (Part A3/A4, Nov 6). Restarts vLLM when a cell needs a
# different config. Cells (run in the order given), MODE:RATE with MODE in
#   stock           FCFS server, gateway with no policy
#   both            priority server, gateway --priority --admission $GW_K
#   reqcap32/64     FCFS server with --max-num-seqs 32/64, load generator direct to vLLM (no gateway)
#   direct          FCFS server, load generator direct to vLLM
#   sbatch --job-name=a3_reqcap slurm/gw_multi.sbatch reqcap64:250 both:250 reqcap32:250
#   sbatch --job-name=a4_collapse slurm/gw_multi.sbatch stock:210 both:210 both:230 stock:230
# Knobs: GW_K (default 77), GW_WARMUP, GW_MEASURE, GW_DRAIN (Part A: 60 / 300 / 180), GW_SEED, GW_BRIEFS (none).
# Cost: cells ~1 + 5 + <=3 min, server (re)start ~3-5 min; 3-4 cells -> ~45 min -> ~0.19 node-h; --time 1:30 caps at 0.375.
#SBATCH --job-name=gw_multi
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=01:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
GW_WARMUP=${GW_WARMUP:-60}; GW_MEASURE=${GW_MEASURE:-300}; GW_DRAIN=${GW_DRAIN:-180}; GW_K=${GW_K:-77}
source harness/gateway/gw_lib.sh
export VLLM_SERVER_DEV_MODE=1
BRIEF_ARGS=()
if [[ -n ${GW_BRIEFS:-} && ${GW_BRIEFS} != none ]]; then
  bn=$(basename "$GW_BRIEFS" .jsonl); BRIEF_ARGS=(--briefs "$GW_BRIEFS" --brief-name "${bn#briefs_}")
fi
gw_export_agent
OUT=$DBKV_DATA/runs/gw_multi/$SLURM_JOB_ID; mkdir -p "$OUT"
PORT=$(gw_free_port); URL=http://127.0.0.1:$PORT; GWPORT=$(gw_free_port); GWURL=http://127.0.0.1:$GWPORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID cells: $* K=$GW_K W=$GW_WARMUP M=$GW_MEASURE drain=$GW_DRAIN repo $(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,memory.total --format=csv
trap gw_cleanup EXIT
CUR=""
for cell in "$@"; do
  mode=${cell%%:*}; rate=${cell##*:}; D="$OUT/${mode}_r${rate}"; mkdir -p "$D"
  case $mode in
    stock|direct) cfg="fcfs|" ;;
    both)         cfg="priority|" ;;
    reqcap*)      cfg="fcfs|--max-num-seqs ${mode#reqcap}" ;;
    *) echo "unknown mode $mode"; continue ;;
  esac
  if [[ $cfg != $CUR ]]; then
    [[ -n $CUR ]] && gw_stop_vllm
    GW_VLLM_EXTRA=${cfg#*|} gw_start_vllm 0 $PORT "$OUT/server_${mode}.log" ${cfg%%|*} || { echo "server failed for $cell"; CUR=""; continue; }
    CUR=$cfg
  fi
  echo "$(date -Is) cell $mode rate=$rate/min (server ${cfg})"
  gw_wait_idle $URL
  curl -s -X POST $URL/reset_prefix_cache >/dev/null || true
  case $mode in
    direct|reqcap*) gw_loadgen "$D" $URL $rate $URL "${BRIEF_ARGS[@]}" ;;
    stock) gw_start_gateway $GWPORT "$D/gateway.jsonl" --backends $URL || continue
           gw_loadgen "$D" $GWURL $rate $URL --gateway "${BRIEF_ARGS[@]}"; gw_stop_gateway ;;
    both)  gw_start_gateway $GWPORT "$D/gateway.jsonl" --backends $URL --priority --admission $GW_K || continue
           gw_loadgen "$D" $GWURL $rate $URL --gateway "${BRIEF_ARGS[@]}"; gw_stop_gateway ;;
  esac
done
python "$GWDIR/summarize.py" "$OUT" > /dev/null && cat "$OUT/summary.md"
echo "$(date -Is) done"
