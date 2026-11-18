#!/usr/bin/env bash
# Idempotent Perlmutter setup for dbkv. Safe to re-run; each step skips if already done.
# Run on a login node:  bash setup/perlmutter_setup.sh [--model]
#   --model  also download $DBKV_MODEL into $HF_HOME (run inside tmux; needs Aryan's approval)
#            Qwen/Qwen3-32B (PLAN 2j): ~65 GB BF16. Qwen/Qwen3-8B (the 8B record): 16.4 GB.
#            Skips the download if the snapshot is already complete; resumes a partial one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/env.sh"

echo "== 1. Data dirs"
mkdir -p "$DBKV_DATA"/{tpch,bird,traces,runs,logs}

echo "== 2. Python env at $DBKV_ENV"
mkdir -p "$(dirname "$DBKV_ENV")"
chmod 700 "$(dirname "$DBKV_ENV")"
if [ ! -f "$DBKV_ENV/bin/activate" ]; then
  module load "$DBKV_PY_MODULE"
  python -m venv "$DBKV_ENV"
fi
# shellcheck disable=SC1091
source "$DBKV_ENV/bin/activate"
python -m pip install -q --upgrade pip
python -m pip install -q -r "$DBKV_REPO/requirements.txt" -r "$HERE/requirements-gpu.txt"

echo "== 2b. Phase 2 extras (PLAN 2j): suffix decoding + our vLLM plugins"
# arctic-inference provides vLLM's "suffix" speculative method. Its C++20 build needs GCC 13 (system g++ 7.5 is too old,
# and GCC 14 output needs a newer libstdc++ than NERSC Python bundles); --no-deps keeps torch/vLLM as they are.
# Never use its [vllm] extra (it pins vllm 0.10.1). See docs/PERLMUTTER.md, 2026-11-07.
if ! python -c "import arctic_inference" 2>/dev/null; then
  CC=/opt/cray/pe/gcc-native/13/bin/gcc CXX=/opt/cray/pe/gcc-native/13/bin/g++ \
    python -m pip install -q --no-deps --no-cache-dir arctic-inference==0.1.1
fi
# Our own plugins, editable and inert unless switched on: per-step engine log (DBKV_STEPLOG), option C
# (DBKV_JOINTSPEC=1), option E (DBKV_TASKEVICT=1).
for pkg in vllm_steplog vllm_jointspec vllm_taskevict; do
  python -m pip install -q --no-deps --no-build-isolation -e "$DBKV_REPO/harness/$pkg"
done

echo "== 3. Exact versions (committed lock: setup/requirements.lock.txt; set DBKV_FREEZE=1 to rewrite it)"
if [[ ${DBKV_FREEZE:-0} == 1 ]]; then python -m pip freeze > "$HERE/requirements.lock.txt"; fi
python - <<'EOF'
import sys, duckdb, vllm, torch
print(f"python {sys.version.split()[0]} | duckdb {duckdb.__version__} | vllm {vllm.__version__} | torch {torch.__version__}")
EOF

if [[ "${1:-}" == "--model" ]]; then
  echo "== 4. Download $DBKV_MODEL to $HF_HOME"
  log="$DBKV_DATA/logs/model_download_$(echo "$DBKV_MODEL" | tr '/' '_').log"
  hf download "$DBKV_MODEL" --exclude "*.pth" >"$log" 2>&1   # hf resumes partial files and skips complete ones
  snap=$(ls -d "$HF_HOME/hub/models--${DBKV_MODEL//\//--}/snapshots/"* | head -1)
  echo "model download finished: $snap ($(du -shL "$snap" | cut -f1)); log $log"
fi
echo "== done"
