#!/bin/bash
# Tier-2 item 5: build $SCRATCH/envs/continuum-env from vllm-continuum (vLLM 0.10.2 base, torch 2.8.0).
# Source: $SCRATCH/src/vllm-continuum (git clone of github.com/Hanchenli/vllm-continuum, commit 316a587).
# Try precompiled first: VLLM_USE_PRECOMPILED=1 reuses the C++/CUDA kernels from the stock
# vllm-0.10.2 wheel and installs Continuum's Python on top (Continuum's changes are Python-side:
# vllm/v1/core/sched/scheduler.py, vllm/v1/core/estimate_with_func.py, config). If that fails, fall
# back to a full source build (MAX_JOBS=32, sm_80 only).
# Cost: 16 physical cores = 1/8 node-hour per hour. Precompiled ~15 min -> ~0.03; a source build can
# take ~1.5 h -> ~0.2; the 2 h limit caps it at 0.25.
#SBATCH --job-name=continuum_env
#SBATCH --account=m4999
#SBATCH --constraint=cpu
#SBATCH --qos=shared
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --time=02:00:00
#SBATCH --output=/pscratch/sd/a/ap2568/dbkv/logs/%x-%j.out
set -uo pipefail
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
deactivate 2>/dev/null || true          # don't build on top of dbkv-env
ENV=$SCRATCH/envs/continuum-env
SRC=$SCRATCH/src/vllm-continuum
WHEELS=$SCRATCH/src/wheels
export PIP_CACHE_DIR=$SCRATCH/cache/pip TMPDIR=$SCRATCH/tmp
mkdir -p "$WHEELS" "$TMPDIR"
echo "$(date -Is) $(hostname) job $SLURM_JOB_ID: building $ENV from $SRC ($(git -C "$SRC" rev-parse --short HEAD))"

python -m venv "$ENV" && source "$ENV/bin/activate"
pip install -q --upgrade pip uv
uv pip install -q "torch==2.8.0" "torchvision==0.23.0" "torchaudio==2.8.0" \
  --index-url https://download.pytorch.org/whl/cu128 || { echo "torch install failed"; exit 1; }

# 1) precompiled kernels from the stock 0.10.2 wheel
pip download -q --no-deps "vllm==0.10.2" -d "$WHEELS"
WHL=$(ls "$WHEELS"/vllm-0.10.2-*.whl | head -1)
echo "precompiled wheel: $WHL"
cd "$SRC"
if VLLM_USE_PRECOMPILED=1 VLLM_PRECOMPILED_WHEEL_LOCATION="$WHL" uv pip install -e . ; then
  echo "$(date -Is) precompiled install OK"
else
  # 2) full source build
  echo "$(date -Is) precompiled install FAILED; source build"
  python use_existing_torch.py
  uv pip install -q -r requirements/build.txt
  MAX_JOBS=32 TORCH_CUDA_ARCH_LIST="8.0" uv pip install -e . --no-build-isolation || { echo "source build failed"; exit 1; }
fi
uv pip install -q lmcache hf_transfer || echo "lmcache install failed (optional)"

# checks (CPU node: no GPU, so import + CLI only)
python - <<'EOF'
import torch, vllm
print("torch", torch.__version__, "cuda", torch.version.cuda, "| vllm", vllm.__version__, vllm.__file__)
from vllm.config.scheduler import SchedulerConfig
import typing, vllm.config.scheduler as s
print("scheduler policies:", typing.get_args(s.SchedulerPolicy))
import vllm.v1.core.estimate_with_func as e
print("FIXED_THRESHOLD_CONTINUUM =", e.FIXED_THRESHOLD_CONTINUUM)
EOF
vllm serve --help=all 2>/dev/null | grep -A3 -- "--scheduling-policy" | head -5
pip freeze > "$ENV/requirements.lock.txt"
echo "$(date -Is) done"
