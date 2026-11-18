#!/bin/bash
# Phase 0 (g) smoke test (PLAN 2j), full node, Qwen3-32B TP=4:
#   1. server with instrumentation on (steplog + iteration details + KV eviction metrics):
#      harness/w3/smoke.py (tool-call probe + 20 W3 tasks at concurrency 4; PASS = 0 tasks without SQL),
#      then a fixed burst x3 (harness/w3/burst.py: 64 requests, 2000-token prompts, 256 output tokens);
#   2. restart with instrumentation off: the same burst x3  -> logging-overhead control (same job).
#   sbatch --time=00:50:00 slurm/node_smoke.sbatch
# Short form for the debug QOS (30 min max): SMOKE_OFF=0 skips part 2 (the off-server burst; the overhead
# control then runs in the Phase 1 sweep job):
#   SMOKE_OFF=0 sbatch -q debug --time=00:30:00 slurm/node_smoke.sbatch
# Estimate: 2 server starts (~5-10 min each, the first compiles) + agent ~5 min + bursts ~4 min -> ~0.4-0.5 node-h.
#SBATCH --job-name=n32_smoke
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=regular
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=128
#SBATCH --time=00:50:00
set -uo pipefail
# Submit from the repo root (setup/dbkv-sbatch does this and puts the log in $DBKV_DATA/logs).
source "${SLURM_SUBMIT_DIR:-$PWD}/setup/env.sh" || { echo "submit from the repo root"; exit 1; }
cd "$DBKV_REPO"
source slurm/node_lib.sh
JOB=${SLURM_JOB_ID:-local$$}
OUT=$DBKV_DATA/runs/node/$JOB; mkdir -p "$OUT"
echo "$(date -Is) $(hostname) job $JOB repo $(git rev-parse --short HEAD)$( [[ -n $(git status --porcelain harness slurm) ]] && echo ' +uncommitted') model $DBKV_MODEL"
node_check_gpus || exit 2
for f in "$DBKV_DATA/w3/streams/w3_mix_s0.jsonl" "$DBKV_DATA/w3/brief_tpch_compact.txt" "$DBKV_DATA/w3/brief_tpcds_compact.txt"; do
  [[ -s $f ]] || { echo "MISSING $f"; exit 1; }
done
[[ ${DRY_RUN:-0} == 1 ]] && { echo "DRY_RUN ok"; exit 0; }
trap 'node_stop_vllm' EXIT
export VLLM_SERVER_DEV_MODE=1   # /reset_prefix_cache for the burst

PORT=$(node_free_port); URL=http://127.0.0.1:$PORT
NODE_STEPLOG=1 node_start_vllm $PORT "$OUT/server_on.log" || exit 3
echo "KV pool: $(node_kv_pool "$OUT/server_on.log") tokens" | tee "$OUT/kv_pool.txt"
python -u harness/w3/smoke.py --url $URL --out "$OUT/smoke" --n 20 --concurrency 4; SMOKE_RC=$?
node_wait_idle $URL
python -u harness/w3/burst.py --url $URL --label steplog_on --out "$OUT/burst_on.json"
curl -s $URL/metrics | grep -E '^vllm:(prefix_cache|num_preemptions|kv_cache_usage)' > "$OUT/metrics_on_end.txt"
node_stop_vllm
if [[ ${SMOKE_OFF:-1} == 0 ]]; then echo "$(date -Is) done (SMOKE_OFF=0: no off-server burst); smoke rc $SMOKE_RC"; exit $SMOKE_RC; fi

PORT=$(node_free_port); URL=http://127.0.0.1:$PORT
NODE_STEPLOG=0 node_start_vllm $PORT "$OUT/server_off.log" || exit 3
python -u harness/w3/burst.py --url $URL --label steplog_off --out "$OUT/burst_off.json"
node_stop_vllm
python - "$OUT" <<'PY'
import json, sys
o = sys.argv[1]
on, off = (json.load(open(f"{o}/burst_{k}.json")) for k in ("on", "off"))
print(f"burst out tok/s: steplog on {on['out_tok_per_s_mean']} vs off {off['out_tok_per_s_mean']} "
      f"-> overhead {100 * (1 - on['out_tok_per_s_mean'] / off['out_tok_per_s_mean']):+.1f}%")
n = sum(1 for _ in open(f"{o}/server_on_steps.jsonl"))
print(f"steplog lines: {n}")
PY
echo "$(date -Is) done; smoke rc $SMOKE_RC"
exit $SMOKE_RC
