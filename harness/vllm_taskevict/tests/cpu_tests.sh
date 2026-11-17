#!/bin/bash
# CPU-node test run for harness/vllm_taskevict (option E). No GPU, no model.
#   srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:20:00 harness/vllm_taskevict/tests/cpu_tests.sh
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh >/dev/null 2>&1
echo "host $(hostname) $(python -V 2>&1) vllm $(python -c 'import vllm; print(vllm.__version__)' 2>/dev/null)"
exec python "$HERE/run_tests.py" "$@"
