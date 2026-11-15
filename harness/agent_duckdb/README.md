# harness/agent_duckdb: the frozen agent on W (PLAN §2h)

> **Next phase (PLAN §2j, Nov 15):** this agent is being ported to **Qwen/Qwen3-32B** (BF16, non-thinking, served with TP = 4) and to the **W3** analytics workload (TPC-H SF10/SF100, TPC-DS SF10, executable gold SQL). The port keeps the loop, prompt, tools and decoding below unless a change is needed for 32B (e.g. the tool-call format in non-thinking mode); every change is listed in a "Port to 32B" section here and frozen as tag **`agent-32b-v1`** after the Phase 0 smoke test (20 tasks, 0 without SQL). The description below is the `agent-duckdb-v1` state.

`run_w.py` and `tools_duckdb.py` are copies of `agent-frozen-v1:harness/agent/run_bird.py` and `tools.py`, kept as close as possible. The loop, SYSTEM prompt, NUDGE and LAST messages, tool specs and texts, decoding (temperature 0, max_tokens 1024, ≤ 15 turns, `tool_choice` "none" on the last turn, `enable_thinking=False`), final-SQL extraction, truncation (40 rows, 3000 chars), error classes and the "real names" hint are unchanged. The prompt and tool texts still say "SQLite", word for word.

What differs from `agent-frozen-v1`, and nothing else:

1. **DuckDB backend** (`tools_duckdb.py`).
   - Each call opens a read-only connection with `SET memory_limit='16GB'; SET threads=8` (PLAN §4a), and a timer thread runs `con.interrupt()` after 60 s.
   - DuckDB errors map onto the frozen classes:
     - `ParserException` → `syntax`
     - "Table with name … does not exist" → `no_such_table`
     - Binder "Referenced column/table … not found" → `no_such_column`
     - interrupt → `timeout`
     - any other DuckDB error → `operational`
   - `describe_table` shows columns, types, PK and foreign keys from `duckdb_constraints()`. TPC-DS from `dsdgen` declares none, and has no description CSVs, so there are no descriptions.
   - The name hint parses with sqlglot's `duckdb` dialect.
2. **Stream task source** (`--stream FILE --n N`).
   - Tasks are the first N questions of a W stream file (`harness/plancache`, format in the W interface).
   - Grading is execution match, pred vs gold result rows as sets, on the task's tenant.
   - Each task row also records `tenant`, `template_id`, `phrasing_id`, `is_repeat` and `pos`. Each turn row also records `turn_type` (`explore` / `execute_sql` / `final`).
3. **One shared brief file** (`--brief FILE`). It is appended as `"\n\nDatabase schema:\n" + brief`, exactly where the frozen agent puts a `--briefs` entry, and is the same for every tenant. `build_s` is 0.
4. **BIRD-only fields dropped.** These are `--bird`, `--seed`, `--brief none|full|oracle`, `--briefs`, `difficulty` (always null), the `SQL` gold and the description CSVs. `evidence` is "" by default, so the `Hint:` line is left out, as in the frozen code.

Also here are `analyze_s.py`, the Test S analysis (S1h–S4h), and the job script `slurm/spec_suffix.sbatch`. The optional BIRD reference cell runs the frozen agent itself, exported from the tag.

## Port to Qwen3-32B and W3 (`agent-32b-v1`, PLAN §2j Phase 0 (f))

What differs from `agent-duckdb-v1`, and nothing else (loop, NUDGE/LAST logic, tool set, decoding, turn limit, truncation, error classes and the name hint are unchanged; the model comes from `DBKV_MODEL` = Qwen/Qwen3-32B):

1. **Dialect wording.** The SYSTEM, NUDGE and LAST texts and the `execute_sql` description say **DuckDB** instead of SQLite, and the prompt says to quote odd names with **double quotes** (DuckDB) instead of backticks. On W the agent was told it was writing SQLite against DuckDB; that is a port bug, not a modelling choice, so it is fixed here before the 32B baseline exists.
2. **One brief per benchmark** (`--brief-map tpch=FILE,tpcds=FILE`). W3 mixes TPC-H and TPC-DS tenants. The briefs are built by `harness/plancache/brief.py` (now also TPC-H: spec PKs and FKs) from `tpch_sf10` and `tpcds_sf10`, stored as `$DBKV_DATA/w3/brief_{tpch,tpcds}_compact.txt` (~0.8k and ~5.2k tokens). The TPC-DS builder still reproduces W's brief byte for byte (checked on `tpcds_sf1`).
3. **Grading from stored gold rows.** A W3 task carries `gold_rows` (canonical, from `harness/w3/build_w3.py`), so SF100 gold queries are not re-run inside GPU jobs. The prediction is executed once (≤ 1001 rows fetched) and compared as a set after `tools_duckdb.canon()` (numbers as `.10g` floats, dates ISO, else str; identical to `build_w3.canon`). Tasks without `gold_rows` (W streams) are graded exactly as before.
4. **Extra task fields:** `bench`, `gold_runtime_s`, `llm_s` (sum of client-side chat time), `db_wall_s` and `db_queue_s` = `db_wall_s` − `db_s` (thread-pool wait + connect, i.e. DB queue time); tool records get `wall_s`. Together: the per-task LLM time, query time and DB queue time (Phase 1 instrumentation).

Frozen as tag **`agent-32b-v1`** after the smoke test passed (job 61369427: 0/20 no-SQL, tool calls parsed). Smoke test: `harness/w3/smoke.py` inside `slurm/node_serve.sbatch` (20 tasks of `w3_mix_s0`, concurrency 4; pass = 0 tasks without SQL and a parsed tool call in non-thinking mode).
