# Source this on Perlmutter (login node or inside a Slurm job):
#   source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
# Single source of truth for paths; perlmutter_setup.sh and job scripts use it.

export DBKV_REPO=/global/cfs/cdirs/m4999/team19/ap2568/dbkv
export DBKV_DATA=$SCRATCH/dbkv                                   # DuckDB files, traces, raw results
export DBKV_ENV=/global/common/software/m4999/ap2568/dbkv-env    # Python venv: CPU tools + stock vLLM
export HF_HOME=$SCRATCH/huggingface                              # shared HF cache (already holds HW models)
export DBKV_MODEL=Qwen/Qwen3-8B
export DBKV_PY_MODULE=python/3.11-24.1.0

module load "$DBKV_PY_MODULE" >/dev/null 2>&1
if [ -f "$DBKV_ENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$DBKV_ENV/bin/activate"
fi
