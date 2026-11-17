# harness: agent, briefs, gateway, and the G3 / D5 tools

- `replay.py`: G3 synthetic session replayer against a running vLLM server (random-token sessions, sampled SQL pauses, exact prefix extension so prefix caching can hit).
- `kv_limit.py`: predicted KV-memory limit (concurrent resident sessions) for a model under vLLM. Pure arithmetic; safe on a login node. Being extended in PLAN §2j Phase 0 (d) for Qwen3-32B with tensor parallelism (KV split over 4 GPUs) and the gateway admission limit K.
- `g3_summarize.py`: turns a G3 sweep directory into `results/g3_table.csv` and `results/g3_summary.md`.
- `d5_probe.py` / `d5_analyze.py`: Test 1 (D5) idle probe of per-request overhead, and its pre-registered analysis (`results/d5_summary.md`).
- `agent_duckdb/`: the agent on DuckDB. W port of the frozen agent (tag `agent-duckdb-v1`, Qwen3-8B); ported to Qwen3-32B and the W3 analytics workload in PLAN §2j (tag `agent-32b-v1`).
- `plancache/`: W and W2 templates (TPC-DS 99, TPC-H 22) and stream generators. W3 (§2j) adds executable gold SQL at TPC-H SF10/SF100 and TPC-DS SF10 on top of them.
- `agent/`: the minimal ReAct SQL agent on BIRD dev. `run_bird.py` (Qwen3-8B via vLLM native tool calling, ≤ 15 turns), `tools.py` (SQLite tools `list_tables`, `describe_table`, `sample_rows`, `execute_sql`), `analyze.py` (Tests 2 and 3). Frozen as tag `agent-frozen-v1`.
- `brief/`: schema briefs built from the database alone. `build.py` (full, compact, lexical, oracle), `llm_select.py` (llm arm), `analyze_d2.py` (step 5), `analyze_sweep.py` (step 6), `stage_metrics.py` (Stage A).
- `gateway/`: `gateway.py` (aiohttp proxy in front of vLLM: admission, task-start priority, routing), `loadgen.py` (open-loop Poisson load running the frozen agent), `mock_vllm.py` (login-node tests), `summarize.py` (per-cell p50/p95, throughput, accuracy), `gw_lib.sh` (shell helpers for `slurm/gw_phase*.sbatch`).

## Goodput gateway (PLAN §2j option B; all flags off by default)

Built on top of A(a) (`--admission K --priority`) in `gateway/gateway.py`. Files: `gateway/goodput.py` (task state from a request's `messages`, the lookup table, the force-final rewrite), `gateway/fit_goodput.py` (fits the table from run directories), `gateway/test_goodput.py` (login-node tests with `mock_vllm.py`, no GPU).

- **State** per request, from the tool channel: turn, tenant (`x-db`), SQL timeouts, other tool errors, turns since the last good `execute_sql`, what the previous turn did, nudges, and output tokens so far (the gateway sums `usage.completion_tokens` per task).
- **Table:** binned states, coarse to fine, each bin shrunk toward its parent (pseudo-count `--m`, default 20). Each bin stores P(task correct), E[remaining output tokens], E[remaining uncached prompt tokens] and E[remaining tool seconds]. Lookup takes ~50 µs.
- **Fit:** `python harness/gateway/fit_goodput.py RUN_DIRS... --out T.json [--seeds 0 | --exclude-seeds 1,2] [--exclude-cells open_140,open_180] [--eval-seeds 1,2] [--compare OTHER.json] [--turn-limits]`. Training is selected by stream seed (qid `w3mix-s<seed>-<pos>`). It writes `T.json` and `T.report.json` (rates by turn, timeouts and errors; held-out scores per table level; static turn-limit view).

| Flag | Effect |
|---|---|
| `--goodput T.json` | vLLM priority = `round(-1000 · log10(p / work))` (higher value is served sooner), with work = out + w_pre · uncached prompt (+ w_db · tool seconds). Replaces the task-start priority of `--priority`. vLLM needs `--scheduling-policy priority` |
| `--prefill-weight W`, `--db-weight W` | Override the table's work weights (defaults 1 and 0: LLM tokens only) |
| `--goodput-admit` | Order the admission queue by the first request's value instead of `x-task-start` |
| `--force-final THRESH` | Needs `--goodput`. Applies only while more than THRESH tasks wait for admission. A request at turn ≥ `--force-min-turn` (2) whose task value is among the lowest `--force-frac` (0.1) of the active tasks gets a forced final answer. This is the agent's own last turn: the `LAST` user message is appended and `tool_choice` is set to `"none"`. The rewrite is sticky for the task, the request gets priority 0, and the gateway logs `ev: force_final` |
| `--turn-limit N` | Static baseline: every request at turn ≥ N gets the same rewrite (`reason: turn_limit`). Works with or without `--goodput` |

The request log gains a `gp` field (turn, timeouts, errors, out_tok, p, work, value, table level, forced). `/gw/stats` gains `forced_goodput`, `forced_turn_limit` and `forced_requests`.
## `w3/dbsched.py`: option D, EXPLAIN query scheduling (PLAN §2j, Phase 2)

A DuckDB query scheduler that the W3 load generator installs as the event loop's **default executor**, so the frozen agent (`agent-32b-v1`, unchanged) is scheduled without edits: its `asyncio.to_thread(tools.call, db, name, args)` and grading `to_thread(tools.run_query, ...)` arrive as `functools.partial(ctx.run, fn, *args)`, from which the scheduler reads the tool, the SQL and the task's contextvar (task id, task start).

- **Switch:** `loadgen_w3.py --db-sched off|explain|observe`. `off` (default) is the Phase 1 plain `ThreadPoolExecutor(--db-workers)`, unchanged. `observe` is FIFO like off, plus the per-call log with classes computed in the background. `explain` is D.
- **Classes:** `EXPLAIN (FORMAT JSON)` on a small classifier pool (with the agent's connection settings), the G2 plan features (`calib/g2_run.plan_features`), and a log-linear model (`w3/dbsched_model.json`, fit on G2's SF100 queries plus the Phase 1 agent SQL) → short (< 0.25 s) / medium / long (predicted ≥ `long_decide_s` = 1.0 s; the true class boundary is 2 s, but the model under-predicts agent SQL). `list_tables`, `describe_table` and `sample_rows` are `meta`; SQL whose EXPLAIN fails is `error` (it fails fast).
- **Scheduling:** at most `--db-workers` calls at once (as off). Order: meta/error, then short, medium, long; within a class by task start (`--db-sched-order taskstart`, the GPU gateway's task-start priority) or FIFO. Caps: `--db-sched-long-cap` long and `--db-sched-heavy-cap` heavy (medium, long, or running longer than 2 s) calls at once; blocked calls are skipped so later ones backfill. A call waiting more than `--db-sched-starve-s` goes first and ignores the heavy cap.
- **Deadline:** `--db-sched-deadline-s` (default 60 = the agent's timeout) counts from submission. At the deadline the call is interrupted (the agent's `tools.connect` is wrapped at runtime to register its connections), so the agent sees DuckDB's own timeout error. Without it, D removes the load shedding that the 60 s timeout gives under overload, and the long backlog grows.
- **`--db-threads N`** (any mode): DuckDB's `threads` and `memory_limit` are **per database instance**, and all connections to one file in one process share one instance (duckdb 2.0.0). So the agent's `SET threads=8` means 8 threads for *all* concurrent queries on that file, not per query. This flag overrides the tools module's `THREADS` constant. Default: unchanged.
- **Logs:** `dbsched.jsonl` holds one row per DuckDB call: class, prediction, EXPLAIN ms, wait, run, runtime, error, whether it was demoted or shed, and the running counts. `dbsched_summary.json` holds per-class wait and run percentiles.

`w3/bench_dbsched.py` is the CPU replay benchmark: `extract`, `calib`, `fit`, `run`, `report` (see its docstring). It replays Phase 1 agent tool calls with their recorded LLM gaps through the same `to_thread(tools.call)` path, as closed-loop agents or open-loop arrivals, with arms such as `off,explain,off` in one process. Raw outputs: `$SCRATCH/dbkv/runs/dbsched/`.
