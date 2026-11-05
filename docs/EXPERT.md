# SQL-expert adapter test (expert session, branch `expert`)

Question: does handing SQL *writing* to a SQL-specialized LoRA adapter (a `write_sql(intent)` tool) make the
Qwen3-8B BIRD agent more accurate and shorter than the base agent writing SQL itself, given the same schema brief?
Code: `harness/expert/`. It imports `harness/agent/` and never edits it. GPU budget for this test: **2 node-hours**.

## Status

| Item | State |
|---|---|
| Pre-registration (below) | Written Thu Nov 5 2026, 12:50 PT, before any Stage 0 analysis or Stage 1 data |
| Stage 0 (traces, no GPU) | Not started |
| Stage 1.1 aLoRA support in installed vLLM | Not started |
| Stage 1.2 adapter training data / BIRD-dev contamination | Not started |
| Stage 1.3 runs (a)/(b)/(d) × full/ideal brief | Waiting for Aryan's approval of the adapter download |

## Pre-registration (Thu Nov 5 2026, 12:50 PT; written before any data; never edit, only add observations below)

### Definitions (fixed now)

- **Turn**: one LLM call by the agent (as in PLAN §2b). In arm (d), calls to the adapter made inside `write_sql` are
  **not** agent turns; they are counted and reported separately ("adapter calls"), and their tokens and time are
  included in output tokens, prefill tokens and task time.
- **Failed SQL call**: an `execute_sql` tool call whose error class is not None (no_such_table, no_such_column, syntax,
  operational, timeout, …). In (d), an execution of adapter-written SQL that fails counts the same.
- **Failed-SQL turn**: a turn that issues ≥ 1 failed SQL call.
- **Repair turn**: a turn whose input contains the result of a failed SQL call, i.e. the turn right after a
  failed-SQL turn in the same task. (A turn can be both; the union is reported as "failed + repair".)
- **Invented-name error**: a SQL execution (any `execute_sql` call, or the final answer SQL at grading) failing with
  `no_such_table` or `no_such_column`. Counted per task (mean per task) for the prediction.
- **Wrong-answer types** (each wrong task gets exactly one, in this order):
  1. *no SQL*: no final SQL and no successful `execute_sql` to fall back on;
  2. *invented names*: the graded SQL fails with no_such_table / no_such_column;
  3. *other SQL error*: the graded SQL fails for another reason (syntax, operational, timeout);
  4. *wrong logic*: the graded SQL runs but its result set differs from gold.
  Also reported, not judged: how many wrong-logic tasks had ≥ 1 invented-name error earlier in the trace.
- **SQL-writing errors** (for the Stage 0 rule) = types 2 + 3 + 4. *No SQL* is not a SQL-writing error.
- **Ideal brief** = Test 3's oracle brief (gold SQL's tables and columns + keys, 3 example values). **Full-schema
  brief** = Test 3's arm (b).
- Accuracy is BIRD execution match as in PLAN §2b; SE = sqrt(p(1−p)/n); paired differences reported with paired SE.

### Predictions (expert (d) vs base agent (a), same brief)

Scored under each brief separately and pooled over both (300 task-runs per arm):
1. accuracy **≥ 8 points** higher;
2. **≥ 50% fewer** invented-name errors per task;
3. **≥ 15% fewer** turns per task;
4. **≥ 10% lower** p50 task time.

### Stop rules

- **Stage 0**: stop (do not run Stage 1) if **repair turns < 15% of turns AND most (> 50%) wrong answers are not
  SQL-writing errors**. Judged on the two brief arms Stage 1 will use (Test 3 (b) full and (c) oracle), pooled;
  the plain arms (Test 2 c=1, c=8) are reported only. *Note written now: by these definitions "wrong logic" counts as a
  SQL-writing error, so the second clause can only hold if most wrong answers are no-SQL.*
- **Stage 1**: continue past Stage 1 only if the expert (d) beats **both** (a) and (b) — for each, by **≥ 5 accuracy
  points or ≥ 10% fewer turns** (either criterion, chosen per comparison). Judged pooled over both briefs; the
  per-brief results are reported. No other conditions are added.

## Observations
