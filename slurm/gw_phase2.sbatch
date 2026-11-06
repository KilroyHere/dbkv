#!/bin/bash
# PLAN 2f Phase 2 (gateway on one GPU) and self-check S2. Frozen agent (tag agent-frozen-v1), open-loop
# Poisson task arrivals over all of BIRD dev, one vLLM server (prefix caching on), cells POLICY:RATE (tasks/min):
#   direct     load generator -> vLLM, no gateway (S2 reference)
#   stock      gateway, no policy (S2 "gateway-no-policy"; Phase 2 stock)
#   admission  gateway --admission $GW_K
#   priority   gateway --priority          (needs vLLM --scheduling-policy priority)
#   both       gateway --priority --admission $GW_K
# One job = one server config: {direct, stock, admission} run on a FCFS server, {priority, both} on a priority
# server; mixing the two groups in one job is refused.
#   sbatch --job-name=gw_s2 --time=01:00:00 slurm/gw_phase2.sbatch direct:R stock:R
#   GW_K=K sbatch --job-name=gw_p2_fcfs slurm/gw_phase2.sbatch stock:R1 admission:R1 stock:R2 admission:R2 ...
#   GW_K=K sbatch --job-name=gw_p2_prio slurm/gw_phase2.sbatch priority:R1 both:R1 ...
# Env knobs: GW_K, GW_WARMUP=120, GW_MEASURE=480, GW_DRAIN=600 (cap after last arrival), GW_SEED=0,
#   GW_BRIEFS (default none = explore agent; or a briefs_<name>.jsonl path).
# Output: $DBKV_DATA/runs/gw_phase2/$SLURM_JOB_ID/<policy>_r<rate>/ + summary.{md,json} for the job.
# Cost: a cell is ~W + 8 min + drain (~1-5 min) ~= 12-15 min (worst 20). 1 GPU shared = 1/4 node-h per hour.
#   S2 (2 cells): ~30 min -> ~0.13 node-h. 6 cells: ~1.4 h -> ~0.35 node-h; --time 2:30 caps it at 0.63.
#SBATCH --job-name=gw_phase2
#SBATCH --account=m4999_g
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=02:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
source harness/gateway/gw_lib.sh
[[ $# -ge 1 ]] || { echo "usage: gw_phase2.sbatch POLICY:RATE ..."; exit 2; }

SCHED=""
for cell in "$@"; do
  case ${cell%%:*} in
    direct|stock|admission) want=fcfs ;;
    priority|both) want=priority ;;
    *) echo "unknown policy in $cell"; exit 2 ;;
  esac
  [[ -z $SCHED || $SCHED == $want ]] || { echo "cells need both a FCFS and a priority server: split the job"; exit 2; }
  SCHED=$want
  [[ ${cell%%:*} == admission || ${cell%%:*} == both ]] && [[ -z ${GW_K:-} ]] && { echo "set GW_K for $cell"; exit 2; }
done

BRIEF_ARGS=()
if [[ -n ${GW_BRIEFS:-} && ${GW_BRIEFS} != none ]]; then
  bn=$(basename "$GW_BRIEFS" .jsonl); BRIEF_ARGS=(--briefs "$GW_BRIEFS" --brief-name "${bn#briefs_}")
fi
gw_export_agent
OUT=$DBKV_DATA/runs/gw_phase2/$SLURM_JOB_ID; mkdir -p "$OUT"
PORT=$(gw_free_port); URL=http://127.0.0.1:$PORT
GWPORT=$(gw_free_port); GWURL=http://127.0.0.1:$GWPORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID server=$SCHED cells: $* K=${GW_K:-} W=$GW_WARMUP M=$GW_MEASURE" \
     "drain=$GW_DRAIN seed=$GW_SEED briefs=${GW_BRIEFS:-none} repo $(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=name,memory.total --format=csv
trap gw_cleanup EXIT
gw_start_vllm 0 $PORT "$OUT/server.log" $SCHED || exit 1

for cell in "$@"; do
  pol=${cell%%:*}; rate=${cell##*:}; D="$OUT/${pol}_r${rate}"; mkdir -p "$D"
  echo "$(date -Is) cell $pol rate=$rate/min"
  gw_wait_idle $URL
  case $pol in
    direct)    gw_loadgen "$D" $URL $rate $URL "${BRIEF_ARGS[@]}"; continue ;;
    stock)     FLAGS=() ;;
    admission) FLAGS=(--admission $GW_K) ;;
    priority)  FLAGS=(--priority) ;;
    both)      FLAGS=(--priority --admission $GW_K) ;;
  esac
  gw_start_gateway $GWPORT "$D/gateway.jsonl" --backends $URL "${FLAGS[@]}" || continue
  gw_loadgen "$D" $GWURL $rate $URL --gateway "${BRIEF_ARGS[@]}"
  gw_stop_gateway
done
python "$GWDIR/summarize.py" "$OUT" > /dev/null && cat "$OUT/summary.md"
echo "$(date -Is) done"
