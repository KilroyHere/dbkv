#!/usr/bin/env bash
# Idempotent Perlmutter setup for dbkv. Safe to re-run; each step skips if already done.
# Run on a login node:  bash setup/perlmutter_setup.sh [--model]
#   --model  also download $DBKV_MODEL into $HF_HOME (~16 GB; run inside tmux)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/env.sh"

echo "== 1. Data dirs"
mkdir -p "$DBKV_DATA"/{tpch,bird,traces,runs,logs}

echo "== 2. Python env at $DBKV_ENV"
mkdir -p "$(dirname "$DBKV_ENV")"
chmod 700 "$(dirname "$DBKV_ENV")"   # group m4999 is the whole class; keep this private
if [ ! -f "$DBKV_ENV/bin/activate" ]; then
  module load "$DBKV_PY_MODULE"
  python -m venv "$DBKV_ENV"
fi
# shellcheck disable=SC1091
source "$DBKV_ENV/bin/activate"
python -m pip install -q --upgrade pip
python -m pip install -q -r "$DBKV_REPO/requirements.txt" -r "$HERE/requirements-gpu.txt"

echo "== 3. Record exact versions"
python -m pip freeze > "$HERE/requirements.lock.txt"
python - <<'EOF'
import sys, duckdb, vllm, torch
print(f"python {sys.version.split()[0]} | duckdb {duckdb.__version__} | vllm {vllm.__version__} | torch {torch.__version__}")
EOF

if [[ "${1:-}" == "--model" ]]; then
  echo "== 4. Download $DBKV_MODEL to $HF_HOME"
  hf download "$DBKV_MODEL" --exclude "*.pth" >"$DBKV_DATA/logs/model_download.log" 2>&1
  echo "model download finished"
fi
echo "== done"
