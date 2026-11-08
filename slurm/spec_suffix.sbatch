#!/bin/bash
# Test S (PLAN §2h): suffix decoding off vs on, on the shared workload W, with the DuckDB port of the frozen
# agent (harness/agent_duckdb/run_w.py). A FRESH vLLM server per cell, so neither the suffix global tree
# (reset_prefix_cache does not clear it) nor the prefix cache carries over between cells.
# Cells, run in the order given:
#   ARM:STREAM:N:C   ARM in off|on|smoke; STREAM = rNN (-> $SPEC_STREAMS/w_rNN_s$SPEC_SEED.jsonl) or a path;
#                    first N questions at concurrency C. smoke = arm off + the no-SQL abort check (> 30% -> exit 3).
#   bird_off:N:C / bird_on:N:C   the frozen agent exported from tag agent-frozen-v1, BIRD dev, --seed 0, no brief.
# Arm "on" adds only --speculative-config '{"method":"suffix"}' (vLLM 0.33 defaults: tree depth 24 =
# num_speculative_tokens, max cached requests 10000, max spec factor 1.0, min token prob 0.1).
# §2h plan (arm order alternates by block):
#   sbatch --job-name=spec_suffix slurm/spec_suffix.sbatch smoke:r80:20:1 \
#     off:r80:150:1 on:r80:150:1   on:r80:150:4 off:r80:150:4   off:r80:300:16 on:r80:300:16 \
#     on:r80:300:64 off:r80:300:64   off:r00:150:4 on:r00:150:4   on:r50:150:4 off:r50:150:4 \
#     bird_off:150:1 bird_on:150:1
# Knobs: DRY_RUN=1 (check exports/streams/brief/tenants, print the plan, exit before vLLM), SPEC_STREAMS,
# SPEC_SEED (0), SPEC_BRIEF, SPEC_SMOKE_MAX (0.30), SPEC_AGENT_REF (git ref to export harness/agent_duckdb
# from, e.g. agent-duckdb-v1; default: copy of the working tree at job start), SPEC_MOCK=1 (login-node test:
# harness/gateway/mock_vllm.py instead of vLLM).
# Outputs: $DBKV_DATA/runs/spec_suffix/<job>/<cell>/{tasks,turns,metrics}.jsonl, server_<cell>.log, <cell>.log,
# spec_config.txt (resolved speculative config per cell), suffix_defaults.txt, SMOKE_PASS|SMOKE_FAIL.
# Cost: 15 server starts x ~3-4 min ~ 55 min; agent time ~100 min (c=1 150q ~15 min per arm, c=4 ~5 min,
# c=16/64 300q ~5 min, BIRD c=1 ~7 min per arm) -> ~2.5-3 h -> ~0.65-0.75 node-h; --time 4:00 caps at 1.0.
#SBATCH --job-name=spec_suffix
#SBATCH --account=m4999_g
# A100-40GB only: plain "gpu" can land on 80GB nodes.
#SBATCH --constraint=gpu&hbm40g
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd "$DBKV_REPO"
source harness/gateway/gw_lib.sh   # gw_export_agent, gw_start_vllm, gw_stop_vllm, gw_free_port, gw_cleanup; sets BIRD
JOB=${SLURM_JOB_ID:-local$$}
STREAMS=${SPEC_STREAMS:-$DBKV_DATA/plancache/streams}; SEED=${SPEC_SEED:-0}
BRIEF=${SPEC_BRIEF:-$DBKV_DATA/plancache/brief_tpcds_compact.txt}
SMOKE_MAX=${SPEC_SMOKE_MAX:-0.30}
SPEC_FLAG='--speculative-config {"method":"suffix"}'   # no spaces: gw_start_vllm word-splits GW_VLLM_EXTRA
[[ $# -gt 0 ]] || { echo "usage: sbatch slurm/spec_suffix.sbatch CELL..."; exit 1; }
mkdir -p "$DBKV_DATA/tmp"

# --- Exports: frozen BIRD agent (tag agent-frozen-v1) and the DuckDB agent, fixed at job start ---
gw_export_agent   # -> $AGENT_DIR/{run_bird.py,tools.py}
W_DIR=$(mktemp -d -p "$DBKV_DATA/tmp" w_agent.XXXX)
if [[ -n ${SPEC_AGENT_REF:-} ]]; then
  for f in run_w.py tools_duckdb.py; do git show "$SPEC_AGENT_REF:harness/agent_duckdb/$f" > "$W_DIR/$f"; done
  W_REV="$SPEC_AGENT_REF ($(git rev-parse --short "$SPEC_AGENT_REF^{commit}" 2>/dev/null))"
else
  cp harness/agent_duckdb/run_w.py harness/agent_duckdb/tools_duckdb.py "$W_DIR/"
  W_REV="working tree at $(git rev-parse --short HEAD)$( [[ -n $(git status --porcelain harness/agent_duckdb) ]] && echo ' +uncommitted')"
fi

# --- Parse and check the cell plan (no GPU work yet) ---
stream_file() { case $1 in /*) echo "$1" ;; *) echo "$STREAMS/w_${1}_s${SEED}.jsonl" ;; esac; }
ERR=0; NAMES=(); KINDS=(); SRV=(); SFILES=(); NS=(); CS=(); HAS_W=0
for cell in "$@"; do
  IFS=: read -r f1 f2 f3 f4 <<< "$cell"
  case $f1 in
    bird_off|bird_on)
      [[ -z ${f4:-} && $f2 =~ ^[0-9]+$ && $f3 =~ ^[0-9]+$ ]] || { echo "bad cell $cell (want bird_off|bird_on:N:C)"; ERR=1; continue; }
      NAMES+=("${f1}_n${f2}_c${f3}"); KINDS+=(bird); SRV+=(${f1#bird_}); SFILES+=(""); NS+=($f2); CS+=($f3) ;;
    off|on|smoke)
      [[ -n ${f4:-} && $f3 =~ ^[0-9]+$ && $f4 =~ ^[0-9]+$ ]] || { echo "bad cell $cell (want ARM:STREAM:N:C)"; ERR=1; continue; }
      sf=$(stream_file "$f2"); sn=$(basename "$sf" .jsonl); sn=${sn#w_}; sn=${sn%_s$SEED}
      NAMES+=("${f1}_${sn}_n${f3}_c${f4}"); KINDS+=(w); SRV+=($( [[ $f1 == on ]] && echo on || echo off ))
      SFILES+=("$sf"); NS+=($f3); CS+=($f4); HAS_W=1 ;;
    *) echo "bad arm in cell $cell"; ERR=1 ;;
  esac
done
for f in "$AGENT_DIR/run_bird.py" "$AGENT_DIR/tools.py" "$W_DIR/run_w.py" "$W_DIR/tools_duckdb.py"; do
  [[ -s $f ]] || { echo "MISSING export $f"; ERR=1; }
done
python -m py_compile "$AGENT_DIR/run_bird.py" "$AGENT_DIR/tools.py" "$W_DIR/run_w.py" "$W_DIR/tools_duckdb.py" || ERR=1
if [[ $HAS_W == 1 ]]; then [[ -s $BRIEF ]] && echo "brief: $BRIEF ($(wc -c < "$BRIEF") chars)" || { echo "MISSING brief $BRIEF"; ERR=1; }; fi
for i in "${!NAMES[@]}"; do
  if [[ ${KINDS[$i]} == w ]]; then
    python - "${SFILES[$i]}" "${NS[$i]}" <<'PY' || ERR=1
import json, os, sys
path, n = sys.argv[1], int(sys.argv[2])
if not os.path.isfile(path):
    sys.exit(f"MISSING stream {path}")
rows = [json.loads(l) for l in open(path) if l.strip()]
if len(rows) < n:
    sys.exit(f"stream {path}: {len(rows)} questions < N={n}")
need = ("qid", "tenant", "db_path", "template_id", "phrasing_id", "question", "gold_sql", "is_repeat")
bad = [k for k in need if any(k not in r for r in rows[:n])]
if bad:
    sys.exit(f"stream {path}: missing fields {bad}")
dbs = sorted({r["db_path"] for r in rows[:n]})
miss = [d for d in dbs if not os.path.isfile(d)]
if miss:
    sys.exit(f"stream {path}: MISSING tenant files {miss}")
rep = sum(bool(r["is_repeat"]) for r in rows[:n]) / n
print(f"  {os.path.basename(path)} first {n}: repeat rate {rep:.2f}, tenants {sorted({r['tenant'] for r in rows[:n]})}")
PY
  else
    [[ -s $BIRD/dev.json ]] || { echo "MISSING BIRD $BIRD/dev.json"; ERR=1; }
  fi
done
echo "$(date -Is) $(hostname) job $JOB repo $(git rev-parse --short HEAD); frozen agent agent-frozen-v1; W agent $W_REV"
echo "cell plan (fresh server per cell):"
for i in "${!NAMES[@]}"; do
  printf "  %2d %-24s server suffix=%-3s %s n=%s c=%s\n" $((i + 1)) "${NAMES[$i]}" "${SRV[$i]}" \
    "$( [[ ${KINDS[$i]} == w ]] && echo "${SFILES[$i]}" || echo "BIRD dev seed 0 (frozen agent)")" "${NS[$i]}" "${CS[$i]}"
done
if [[ $ERR != 0 ]]; then echo "PLAN CHECK FAILED"; rm -rf "$AGENT_DIR" "$W_DIR"; exit 1; fi
if [[ ${DRY_RUN:-0} == 1 ]]; then echo "DRY_RUN: checks passed, exiting before vLLM"; rm -rf "$AGENT_DIR" "$W_DIR"; exit 0; fi

# --- Run ---
OUT=$DBKV_DATA/runs/spec_suffix/$JOB; mkdir -p "$OUT"
nvidia-smi --query-gpu=name,memory.total --format=csv 2>/dev/null
SP=
trap '[[ -n $SP ]] && kill $SP 2>/dev/null; gw_cleanup' EXIT
if [[ ${SPEC_MOCK:-0} != 1 ]]; then
  python -c "
import dataclasses, vllm
from vllm.config.speculative import SpeculativeConfig
print('vllm', vllm.__version__, {f.name: f.default for f in dataclasses.fields(SpeculativeConfig) if f.name.startswith('suffix_')})
" 2>/dev/null | tee "$OUT/suffix_defaults.txt"
fi

cat > "$W_DIR/sampler.py" <<'PY'
# One /metrics scrape (stdin) -> one JSON line: d2_sweep's gauges/counters plus the spec-decode counters.
import sys, json, time
keep = ("vllm:kv_cache_usage_perc", "vllm:num_requests_running", "vllm:num_requests_waiting",
        "vllm:prefix_cache_queries", "vllm:prefix_cache_hits", "vllm:num_preemptions",
        "vllm:spec_decode_num_drafts", "vllm:spec_decode_num_draft_tokens", "vllm:spec_decode_num_accepted_tokens")
POS = "vllm:spec_decode_num_accepted_tokens_per_pos"
d = {"t": time.time()}
for line in sys.stdin:
    if line.startswith("#") or not line.strip(): continue
    name = line.split("{")[0].split(" ")[0]
    val = float(line.rsplit(" ", 1)[1])
    for k in keep:
        if name in (k, k + "_total"): d[k] = d.get(k, 0.0) + val
    if name in (POS, POS + "_total") and 'position="' in line:
        p = line.split('position="', 1)[1].split('"', 1)[0]
        d.setdefault(POS, {})[p] = d.get(POS, {}).get(p, 0.0) + val
print(json.dumps(d))
PY
sample() {  # $1 = output file, $2 = URL; samples /metrics every 2 s until killed
  while true; do curl -s $2/metrics | python "$W_DIR/sampler.py" >> "$1"; sleep 2; done
}

start_server() {  # $1 = off|on, $2 = log; sets PORT, URL
  PORT=$(gw_free_port); URL=http://127.0.0.1:$PORT
  if [[ ${SPEC_MOCK:-0} == 1 ]]; then
    setsid python harness/gateway/mock_vllm.py --port $PORT --delay ${SPEC_MOCK_DELAY:-0.05} > "$2" 2>&1 &
    SERVER_PIDS+=($!)
    local k; for k in $(seq 1 30); do curl -sf $URL/health >/dev/null && return 0; sleep 1; done
    return 1
  fi
  local extra=""; [[ $1 == on ]] && extra=$SPEC_FLAG
  GW_VLLM_EXTRA=$extra gw_start_vllm 0 $PORT "$2" fcfs
}

STARTED=0
for ci in "${!NAMES[@]}"; do  # not i: gw_start_vllm loops over a global i
  name=${NAMES[$ci]}; D="$OUT/$name"; mkdir -p "$D"; arm=${SRV[$ci]}
  [[ $STARTED == 1 ]] && gw_stop_vllm
  echo "$(date -Is) cell $name: starting fresh server (suffix $arm)"
  if ! start_server $arm "$OUT/server_$name.log"; then
    echo "server failed for $name"; tail -20 "$OUT/server_$name.log"; STARTED=1
    [[ $name == smoke_* ]] && { echo "smoke $name: server failed" > "$OUT/SMOKE_FAIL"; echo "SMOKE_FAIL: server failed"; exit 3; }
    continue
  fi
  STARTED=1
  { echo "== $name (suffix $arm)"; grep -iE "speculative|suffix" "$OUT/server_$name.log" | cut -c1-600 | head -20; } >> "$OUT/spec_config.txt"
  nspec=$(grep -ciE "speculative_config=SpeculativeConfig|method='suffix'|suffix" "$OUT/server_$name.log")
  echo "  server log lines mentioning speculative/suffix: $nspec"
  grep -oE "speculative_config=(None|SpeculativeConfig\([^)]*\))" "$OUT/server_$name.log" | head -1
  [[ $arm == on && $nspec == 0 && ${SPEC_MOCK:-0} != 1 ]] && echo "  WARNING: arm on but no suffix line in the server log"
  echo "$(date -Is) cell $name: running"
  sample "$D/metrics.jsonl" $URL & SP=$!
  if [[ ${KINDS[$ci]} == bird ]]; then
    python "$AGENT_DIR/run_bird.py" --url $URL --bird "$BIRD" --n ${NS[$ci]} --seed 0 --concurrency ${CS[$ci]} \
      --out "$D" > "$OUT/$name.log" 2>&1
  else
    python "$W_DIR/run_w.py" --url $URL --stream "${SFILES[$ci]}" --n ${NS[$ci]} --concurrency ${CS[$ci]} \
      --brief "$BRIEF" --out "$D" > "$OUT/$name.log" 2>&1
  fi
  kill $SP 2>/dev/null; wait $SP 2>/dev/null; SP=
  curl -s $URL/metrics | python "$W_DIR/sampler.py" >> "$D/metrics.jsonl"   # final counters after the cell
  tail -1 "$OUT/$name.log"
  if [[ $name == smoke_* ]]; then
    python - "$D/tasks.jsonl" "$SMOKE_MAX" <<'PY'
import json, sys
path, mx = sys.argv[1], float(sys.argv[2])
try:
    t = [json.loads(l) for l in open(path) if l.strip()]
except OSError:
    t = []
bad = sum(r.get("status") != "answered" for r in t)
rate = bad / len(t) if t else 1.0
print(f"SMOKE: no-SQL (status != answered) {bad}/{len(t)} = {rate:.1%} (abort if > {mx:.0%}); "
      f"accuracy {sum(r.get('correct', False) for r in t)}/{len(t)}")
sys.exit(0 if t and rate <= mx else 3)
PY
    if [[ $? != 0 ]]; then
      echo "smoke $name: no-SQL rate above $SMOKE_MAX or no tasks; see $OUT/$name.log" > "$OUT/SMOKE_FAIL"
      echo "SMOKE_FAIL: aborting before any other cell (PLAN §2h). $(cat "$OUT/SMOKE_FAIL")"
      exit 3
    fi
    echo "smoke $name passed" > "$OUT/SMOKE_PASS"
  fi
done
echo "$(date -Is) done; analyze with: python harness/agent_duckdb/analyze_s.py $OUT"
