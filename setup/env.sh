# Source this on Perlmutter (login node or inside a Slurm job):
#   source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
# Single source of truth for paths; perlmutter_setup.sh and job scripts use it.

export DBKV_REPO=/global/cfs/cdirs/m4999/team19/ap2568/dbkv
export DBKV_DATA=$SCRATCH/dbkv                                   # DuckDB files, traces, raw results
export DBKV_ENV=$SCRATCH/envs/dbkv-env                          # Python venv: CPU tools + stock vLLM
# (not /global/common/software/m4999: that quota is shared by the whole class and was full on 2026-11-04)
export HF_HOME=$SCRATCH/huggingface                              # shared HF cache (already holds HW models)
export DBKV_MODEL=Qwen/Qwen3-8B
# JIT/compile caches on $SCRATCH: $HOME doesn't support flock from compute nodes (errno 524),
# which killed FlashInfer's kernel build in job 60824576. Lustre scratch does.
export FLASHINFER_WORKSPACE_BASE=$SCRATCH/cache            # -> $SCRATCH/cache/.cache/flashinfer
export VLLM_CACHE_ROOT=$SCRATCH/cache/vllm                  # torch.compile artifacts
export TRITON_CACHE_DIR=$SCRATCH/cache/triton
export TORCHINDUCTOR_CACHE_DIR=$SCRATCH/cache/inductor
export XDG_CACHE_HOME=$SCRATCH/cache                       # uv, pip and anything else using ~/.cache
export UV_CACHE_DIR=$SCRATCH/cache/uv                        # (uv lock on $HOME failed: job 60825842)
export PIP_CACHE_DIR=$SCRATCH/cache/pip
mkdir -p "$SCRATCH/cache" 2>/dev/null || true
export DBKV_PY_MODULE=python/3.11-24.1.0

module load "$DBKV_PY_MODULE" >/dev/null 2>&1
if [ -f "$DBKV_ENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$DBKV_ENV/bin/activate"
fi
