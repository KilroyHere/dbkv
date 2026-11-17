# dbkv_taskevict: option E (task-aware KV eviction) as a vLLM 0.33 plugin

Design, policy and risks: [engine/E_task_eviction.md](../../engine/E_task_eviction.md).

A vLLM **general plugin** (entry point group `vllm.general_plugins`). It monkeypatches four classes in the
engine-core process and changes no installed file. **It is inert unless `DBKV_TASKEVICT=1`**, so installing
it does not change stock or other runs.

## Install (Aryan; not done by the agent)

Our own code, no download, editable like `dbkv_steplog`:

```bash
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
pip install --no-deps --no-build-isolation -e /global/cfs/cdirs/m4999/team19/ap2568/dbkv/harness/vllm_taskevict
python -c "from importlib.metadata import entry_points as e; print(e(group='vllm.general_plugins'))"   # lists dbkv_taskevict
```

If `VLLM_PLUGINS` is set in a job, it must include `dbkv_taskevict` (and `dbkv_steplog` for the step log).

## Run (GPU job)

Engine (`slurm/node_lib.sh` passes the environment through to `vllm serve`):

```bash
export DBKV_TASKEVICT=1                    # on; unset = stock vLLM
export DBKV_TASKEVICT_MODE=full            # full | ended_only | paused_only | tag_only (overhead control: hooks, no reordering)
export DBKV_TASKEVICT_TTL=300              # s idle (nothing in flight) before a live task's blocks fall back to plain LRU; 0 = never
export DBKV_TASKEVICT_PORT=8899            # task_end listener in the engine-core process (127.0.0.1); 0 = in-band only
export DBKV_TASKEVICT_LOG=$OUT/taskevict.jsonl   # stats every DBKV_TASKEVICT_LOG_EVERY s (default 10)
NODE_VLLM_EXTRA="--scheduling-policy priority"   # needed for policy (iii); already part of A(a)
```

Gateway:

```bash
python harness/gateway/gateway.py ... --priority --taskevict http \
    --taskevict-endpoints http://127.0.0.1:8899/task_end      # one URL per --backends entry
# or --taskevict inband (no listener needed: a 1-token request carries the end marker)
```

What the engine log shows (`DBKV_TASKEVICT_LOG`, one JSON line per 10 s): live / ended / expired task counts,
task_end messages (`end_msgs`, `end_dup`, `end_unseen`), TTL `expirations`, and per pool the free blocks per
tier (`first / ended / normal / paused`), blocks handed out per tier (`popped`), of which still cached
(`evicted`), and PAUSED→ENDED/NORMAL moves. `GET http://127.0.0.1:8899/stats` returns the latest line.

## Tests (CPU node, no GPU)

```bash
srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:20:00 harness/vllm_taskevict/tests/cpu_tests.sh
```

The env has no pytest, so `tests/run_tests.py` runs the plain `test_*` functions (they are pytest-compatible).
`test_tiers.py` checks the queue against vLLM's real `BlockPool`/`FreeKVCacheBlockQueue`;
`test_plugin.py` and `test_scheduler.py` install the plugin in a subprocess and drive vLLM's real
`KVCacheManager` and V1 `Scheduler` (Qwen3-8B config only, `HF_HUB_OFFLINE=1`);
`test_gateway_taskevict.py` runs the gateway against `harness/gateway/mock_vllm.py`.
