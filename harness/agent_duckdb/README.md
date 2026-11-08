# harness/agent_duckdb: the frozen agent on W (PLAN §2h)

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
