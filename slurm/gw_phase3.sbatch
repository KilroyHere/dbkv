#!/bin/bash
# PLAN 2f Phase 3 (routing across vLLM replicas on one node) and self-check S3. Frozen agent with the
# compact per-DB brief by default, open-loop Poisson arrivals over all of BIRD dev.
# First arg = number of replicas (2 for Phase 3; 1 for S3, submitted with --gpus=1); then cells POLICY:RATE:
#   direct        load generator -> replica 0, no gateway
#   single        gateway, every task to replica 0
#   round_robin | least_loaded | affinity     gateway --route ... (affinity cap = GW_CAP, default 1.25)
#   sbatch --job-name=gw_p3 slurm/gw_phase3.sbatch 2 round_robin:R1 least_loaded:R1 affinity:R1 ...
#   sbatch --job-name=gw_s3 --gpus=1 --cpus-per-task=32 --time=01:00:00 slurm/gw_phase3.sbatch 1 direct:R affinity:R
# Env knobs: GW_BRIEFS (default $DBKV_DATA/briefs/briefs_compact.jsonl; "none" = explore agent, as in
#   Phase 2), GW_CAP, GW_WARMUP=120, GW_MEASURE=480, GW_DRAIN=600, GW_SEED=0. Servers are FCFS.
# Output: $DBKV_DATA/runs/gw_phase3/$SLURM_JOB_ID/<policy>_r<rate>/ + summary.{md,json} for the job.
# Cost: a cell ~12-15 min (worst 20); 2 GPUs shared = 1/2 node-h per hour. 6 cells ~1.5 h -> ~0.75 node-h;
#   --time 2:30 caps it at 1.25. S3 (1 GPU, 2 cells, ~30 min) -> ~0.13 node-h.
#SBATCH --job-name=gw_phase3
#SBATCH --account=m4999_g
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=2
#SBATCH --cpus-per-task=64
#SBATCH --time=02:30:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
source harness/gateway/gw_lib.sh
NREP=${1:-}; shift || true
[[ $NREP == 1 || $NREP == 2 ]] && [[ $# -ge 1 ]] || { echo "usage: gw_phase3.sbatch NREP(1|2) POLICY:RATE ..."; exit 2; }
NGPU=$(nvidia-smi -L | wc -l)
[[ $NGPU -ge $NREP ]] || { echo "need $NREP GPUs, have $NGPU (submit S3 with --gpus=1 and NREP=1)"; exit 2; }
for cell in "$@"; do
  case ${cell%%:*} in direct|single|round_robin|least_loaded|affinity) ;; *) echo "unknown policy in $cell"; exit 2 ;; esac
done

GW_BRIEFS=${GW_BRIEFS:-$DBKV_DATA/briefs/briefs_compact.jsonl}
BRIEF_ARGS=()
if [[ $GW_BRIEFS != none ]]; then
  bn=$(basename "$GW_BRIEFS" .jsonl); BRIEF_ARGS=(--briefs "$GW_BRIEFS" --brief-name "${bn#briefs_}")
fi
gw_export_agent
OUT=$DBKV_DATA/runs/gw_phase3/$SLURM_JOB_ID; mkdir -p "$OUT"
PORTS=(); URLS=(); for r in $(seq 0 $((NREP - 1))); do PORTS+=($(gw_free_port)); URLS+=(http://127.0.0.1:${PORTS[r]}); done
BACKENDS=$(IFS=,; echo "${URLS[*]}")
GWPORT=$(gw_free_port); GWURL=http://127.0.0.1:$GWPORT
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID replicas=$NREP cells: $* cap=${GW_CAP:-1.25} W=$GW_WARMUP" \
     "M=$GW_MEASURE drain=$GW_DRAIN seed=$GW_SEED briefs=$GW_BRIEFS repo $(git rev-parse --short HEAD)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv
export VLLM_SERVER_DEV_MODE=1   # enables POST /reset_prefix_cache (S2 fix, Nov 5: reset between cells)
trap gw_cleanup EXIT
# Started one after the other so the second reuses the first's torch.compile cache instead of racing it.
for r in $(seq 0 $((NREP - 1))); do
  gw_start_vllm $r ${PORTS[r]} "$OUT/server$r.log" fcfs || exit 1
done

for cell in "$@"; do
  pol=${cell%%:*}; rate=${cell##*:}; D="$OUT/${pol}_r${rate}"; mkdir -p "$D"
  echo "$(date -Is) cell $pol rate=$rate/min"
  gw_wait_idle "${URLS[@]}"
  for u in "${URLS[@]}"; do curl -s -X POST $u/reset_prefix_cache >/dev/null || true; done   # S2 fix: no cache carry-over
  if [[ $pol == direct ]]; then
    gw_loadgen "$D" ${URLS[0]} $rate ${URLS[0]} "${BRIEF_ARGS[@]}"; continue
  fi
  gw_start_gateway $GWPORT "$D/gateway.jsonl" --backends $BACKENDS --route $pol --cap ${GW_CAP:-1.25} || continue
  gw_loadgen "$D" $GWURL $rate $BACKENDS --gateway "${BRIEF_ARGS[@]}"
  gw_stop_gateway
done
python "$GWDIR/summarize.py" "$OUT" > /dev/null && cat "$OUT/summary.md"
echo "$(date -Is) done"
