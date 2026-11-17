# dbkv_jointspec: option C (joint speculation and prefill budget)

A vLLM 0.33 general plugin that wraps the V1 scheduler. For each step it:
- gives every decoding request its token first;
- shares the rest of the step budget between draft tokens, allocated by estimated acceptance, and prefill.

It does nothing unless `DBKV_JOINTSPEC=1`. Design, line references and risks are in [engine/C_joint_spec.md](../../engine/C_joint_spec.md).

## Install (Aryan; our own code, no download)

```bash
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd $DBKV_REPO
pip install --no-deps --no-build-isolation -e harness/vllm_jointspec
python -c "from importlib.metadata import entry_points; print(entry_points(group='vllm.general_plugins'))"
```

Log it in `docs/PERLMUTTER.md`. While installed but switched off, it is inert: `register()` returns at once, and vLLM's scheduler class is untouched.

If `VLLM_PLUGINS` is ever set, it must include `dbkv_jointspec`.

## Switch and knobs (environment of the `vllm serve` process)

| Variable | Default | Meaning |
|---|---|---|
| `DBKV_JOINTSPEC` | `0` | `1` turns the scheduler wrapper on |
| `DBKV_JOINTSPEC_BUDGET` | `0` | tokens per step; `0` = vLLM's `max_num_scheduled_tokens` |
| `DBKV_JOINTSPEC_THETA` | `0.5` | exchange rate: a draft at position k with p^k ≥ θ beats a prefill token |
| `DBKV_JOINTSPEC_MIN_VALUE` | `0.0` | never verify a draft with p^k below this |
| `DBKV_JOINTSPEC_FILL_LEFTOVER` | `1` | low-value drafts use budget that prefill leaves |
| `DBKV_JOINTSPEC_DECODE_FIRST` | `1` | stably move decodes ahead of running prefill chunks |
| `DBKV_JOINTSPEC_EWMA` | `0.9` | decay of the acceptance counts |
| `DBKV_JOINTSPEC_PRIOR` | `4` | pseudo-trials pulling a request's estimate to the global one |
| `DBKV_JOINTSPEC_P_INIT` | `0.6` | initial global acceptance (Test S: 0.58–0.63) |
| `DBKV_JOINTSPEC_WAIT_HIT` | `0.9` | assumed prefix-cache hit of waiting prompts (demand estimate only) |
| `DBKV_JOINTSPEC_LOG` | empty | JSONL decision log path (`{pid}` expands) |
| `DBKV_JOINTSPEC_LOG_EVERY` | `1` | log every n-th step |

It is only active with a speculative method and synchronous scheduling. Suffix decoding forces synchronous scheduling in vLLM 0.33. The server log says `dbkv_jointspec: ACTIVE` or `inactive`.

**Alternative without the env switch:** `--scheduler-cls dbkv_jointspec.scheduler.JointSpecScheduler` (the knobs still come from the env).

## GPU run (example; with `slurm/node_lib.sh`)

```bash
export NODE_VLLM_EXTRA='--speculative-config {"method":"suffix","num_speculative_tokens":24}'
export DBKV_JOINTSPEC=1 DBKV_JOINTSPEC_THETA=0.5 DBKV_JOINTSPEC_BUDGET=1024 DBKV_JOINTSPEC_MIN_VALUE=0.05
export DBKV_JOINTSPEC_LOG=$OUT/jointspec_{pid}.jsonl
node_start_vllm $PORT $OUT/server.log
```

- `setsid vllm serve` inherits the exports.
- For the static baseline arm, unset `DBKV_JOINTSPEC` and vary `num_speculative_tokens`.

## Tests

The policy tests are pure Python and quick:

```bash
cd harness/vllm_jointspec && python -m unittest tests.test_policy -v
```

The scheduler tests build a real vLLM `Scheduler`, so run them on a CPU node. No GPU or weights are needed, only Qwen3-8B's `config.json` from `$HF_HOME`:

```bash
cd harness/vllm_jointspec && VLLM_TARGET_DEVICE=cpu HF_HUB_OFFLINE=1 \
  srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:20:00 \
  $DBKV_ENV/bin/python -m unittest tests.test_policy tests.test_scheduler -v
```

The tests import the package from the source tree, so they do not need it installed.
