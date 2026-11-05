# SQL-expert adapter test (expert session, branch `expert`)

Question: does handing SQL *writing* to a SQL-specialized LoRA adapter (a `write_sql(intent)` tool) make the
Qwen3-8B BIRD agent more accurate and shorter than the base agent writing SQL itself, given the same schema brief?
Code: `harness/expert/`. It imports `harness/agent/` and never edits it. GPU budget for this test: **2 node-hours**.

## Status

| Item | State |
|---|---|
| Pre-registration (below) | Written Thu Nov 5 2026, 12:50 PT, before any Stage 0 analysis or Stage 1 data |
| Stage 0 (traces, no GPU) | **Done: CONTINUE** by rule (repair 8.7% < 15%, but 90% of wrong answers are SQL-writing errors, almost all wrong logic). `results/expert_stage0.md` |
| Stage 1.1 aLoRA support in installed vLLM | **Done: no.** vLLM 0.33.0 rejects aLoRA adapters explicitly; plain LoRA works. The adapter is plain LoRA anyway |
| Stage 1.2 adapter training data / BIRD-dev contamination | **Done: no BIRD-dev data found.** The docs say BIRD train only. The byte-level check of the 5,160-record split finds 0 dev DBs, 0 dev questions, 0 dev evidence or SQL matches (`results/expert_contam.md`) |
| Stage 1.3 runs (a)/(b)/(d) × full/ideal brief | Approved by Aryan (download + run; merge main for the agent, agent @ 220001e). Submitting, ≈ 0.15 GPU node-h (cap 0.25) |

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

### Stage 0 (Nov 5, 12:53 PT; `harness/expert/stage0.py`, `results/expert_stage0.md`)

Traces: Test 2 (60839247, c=1 and c=8, plain) and Test 3 (60839248, full and oracle briefs, c=8), agent before the
Nov 5 fixes. One aside row: the main session's fixed agent (60872455, agent @ 779bcfd, plain, c=8), reported only.

| arm | acc | turns | failed-SQL turns | repair turns | failed ∪ repair | decode in ∪ | invented-name errs / task |
|---|---|---|---|---|---|---|---|
| T2 plain c=1 | 34.0% | 913 | 13.5% | 13.5% | 25.7% | 28.0% | 0.71 |
| T2 = T3(a) plain c=8 | 36.0% | 915 | 13.1% | 13.1% | 25.1% | 27.6% | 0.70 |
| T3(b) full c=8 | 43.3% | 462 | 9.7% | 9.7% | 17.3% | 15.1% | 0.23 |
| T3(c) oracle c=8 | 54.0% | 444 | 7.7% | 7.7% | 14.0% | 12.0% | 0.14 |
| *aside: fixed agent 779bcfd plain c=8* | *44.7%* | *1084* | *4.1%* | *4.1%* | *7.2%* | *10.8%* | *0.19* |

(Failed and repair shares match because every failed turn is followed by another turn.)

Wrong answers by type:

| arm | wrong | no SQL | invented names | other SQL error | wrong logic (had invented-name errs earlier) |
|---|---|---|---|---|---|
| T2 plain c=1 | 99 | 22 | 0 | 4 | 73 (28) |
| T2 = T3(a) plain c=8 | 96 | 21 | 0 | 2 | 73 (29) |
| T3(b) full | 85 | 10 | 0 | 4 | 71 (13) |
| T3(c) oracle | 69 | 6 | 0 | 2 | 61 (7) |
| *aside: fixed agent* | *83* | *5* | *0* | *3* | *75 (11)* |

- **Rule** (pooled over T3(b) and T3(c)): repair turns are **8.7%** of turns (< 15%, so this clause holds). SQL-writing
  errors are **90%** of 154 wrong answers (not ≤ 50%, so this clause fails). Stop needs both → **CONTINUE**.
- Readings (no rule changed):
  - Invented names never survive into the graded SQL: the agent repairs them, or falls back to an earlier
    successful query. Their cost is turns, and with a brief that cost is small (0.14–0.23 errors per task).
  - Wrong answers are almost all *wrong logic*: the SQL runs but returns the wrong result. That is the error an
    expert writer has to fix.
  - **Headroom for prediction 3 (≥ 15% fewer turns) is thin.** With briefs, failed ∪ repair is only 14–17% of
    turns, so (d) gets ≥ 15% only if it removes nearly all of them, or also removes verification turns.
    Prediction 2 is on small counts (≈ 20–35 invented-name errors per 150 tasks).

### Stage 1.1: Activated LoRA in the installed vLLM (Nov 5)

**Not supported.** vLLM 0.33.0 (`dbkv-env`) has no aLoRA code path. `vllm/lora/peft_helper.py:79-80` rejects any
adapter whose config sets `alora_invocation_tokens`, with "vLLM does not support Activated LoRA (aLoRA)". Plain LoRA
(`--enable-lora --lora-modules`) works. The adapter's `adapter_config.json` has `peft_type: LORA` and
`alora_invocation_tokens: null`, so it is plain LoRA (r 16, α 32, all linear projections) and loads either way. Nothing
was installed.
*Consequence:* LoRA requests can't reuse the agent's base-model KV (vLLM keys the prefix cache by adapter). So each
`write_sql` call prefills its own prompt from scratch, and Stage 1 reports this as adapter prefill tokens.

### Stage 1.2: training data of `craboy4/qwen3-8b-bird-lora-dbdev4` (Nov 5; read from the HF card/configs and GitHub `craboy4/text-to-sql-struct-distillation`, nothing downloaded)

- **Data:** `dbdev4_train_5160.jsonl`, 5,160 SFT records, 3 epochs, LoRA r 16, lr 5e-5. It comes from
  `teacher_generation/generate_teacher_data.py`, run on **BIRD train** (`train_filtered/train.jsonl`,
  `train/train_databases`, `train_column_meaning.json`). A teacher model wrote the outputs: `gpt-5.6-terra` at high
  reasoning, which is the script's default and the teacher named in their results table. The full output is `<schema_linking>`, `<query_plan>`, `<sql>`, kept only if it executes and
  matches gold.
- **Split ("dbdev4"):** it is database-disjoint *within BIRD train*. Four train DBs are held out for an execution-dev
  set (hockey, mondial_geo, movie_3, student_loan), and works_cycles is dropped for length. "dev" here means their
  own dev split of train, **not BIRD dev**.
- **BIRD dev:** the docs say training used **no BIRD dev data**. Their benchmark is BIRD Mini-Dev, 500 questions on
  the 11 dev DBs, which **overlaps BIRD dev**. They evaluated on it and tuned prompt/schema tooling on it
  (`training/*minidev*`). A 500-record Mini-Dev SFT set exists but is "not used in the reported 8B training".
  checkpoint-969 is the **last** step: 5,160/16 ≈ 323 steps × 3 epochs. So no checkpoint was picked on Mini-Dev.
  - Residual risk: indirect, through choices made by looking at Mini-Dev scores. There is no evidence of dev
    examples in the weights.
- **Byte-level check (Nov 5, after Aryan approved the download; `harness/expert/contam.py`, `results/expert_contam.md`).**
  The adapter (sha256 `8940b165…`) and `dbdev4_train_5160.jsonl` (sha256 `1e46c2a8…`) both match the published
  hashes. The split's records carry only `messages` (no `db_id`), so each record's database is identified by the set
  of table names in its schema: 64 distinct schemas.
  - **0 of the 11 BIRD-dev databases** has table-set Jaccard ≥ 0.5 with any SFT schema. The maximum is 0.29, for
    debit_card_specializing.
  - **0 normalized question matches** with the 1,534 dev questions, so 0 with our 150 tasks. 0 matches on long
    evidence text, 0 on target SQL vs dev gold SQL.
  - The system prompt is identical to `harness/expert/expert_system_prompt.txt` in 5,160 of 5,160 records.
  - **Verdict: the adapter saw no BIRD-dev data.** The only residual is indirect: their prompt/tooling choices were
    tuned on Mini-Dev.
- **Its native prompt:** a fixed system prompt with one illustrative example, then a user message "Task / Evidence
  / Complete SQLite schema with column meanings", with the full DDL plus column meanings. Stage 1 (d) uses the same
  system prompt and layout.

### Stage 1.3 design (written Nov 5 before any Stage 1 data; Aryan may veto before the run)

- **Engine:** one vLLM 0.33 server on 1 × A100-40GB (`gpu&hbm40g`), Qwen3-8B with `--enable-lora --max-lora-rank 16
  --lora-modules expert=<adapter>`, prefix caching on and no speculative decoding. All three arms use this same
  server, so LoRA-enabled overhead is shared.
- **Tasks:** the same 150 BIRD-dev tasks (seed 0), concurrency 8, temperature 0, non-thinking, ≤ 15 turns. Briefs:
  `full` and `oracle` (ideal), exactly as Test 3.
- **Runner:** `harness/expert/run_expert.py`. It imports `harness/agent/run_bird.py`, unchanged, and runs its
  `run_task`. Arm (a) is the base agent itself. (b) only appends few-shot examples to the system prompt. (d) only
  adds the `write_sql` tool. The agent commit used is the one recorded at run time, the frozen commit if it exists.
- **(b) few-shot:** 3 fixed examples (question, evidence, the tables used, the gold SQL), the same for every task,
  drawn from **BIRD train** (the adapter's SFT split, so no dev data). Rule: seed 0, one each of simple / moderate /
  challenging, from 3 different DBs.
  - *Amendment (Nov 5, before any Stage 1 data):* the split has no difficulty or `db_id` field. Difficulty is
    therefore the SQL-length tertile (short / medium / long), and a DB is its schema's set of table names.
  - The examples and their SQL are the teacher's execution-verified SQL, not BIRD gold. Chosen
    (`harness/expert/fewshot.json`, ≈ 3.1k chars): a business-review DB (simple filter), an Olympics DB (join +
    GROUP BY/HAVING), and sales_in_weather (3-way join, CTE, argmax).
- **Agent commit (Aryan, Nov 5):** main merged into `expert` before the run, so `harness/agent` is @ **220001e** in
  every arm. The agent is not yet frozen; `expert_config.json` in each run dir records the commit.
- **(d) `write_sql(intent)`:** the agent describes what the query must compute. The adapter gets its native system
  prompt, then *Task* = question + "Analyst's intent: …", *Evidence* = the hint, and as schema **the same brief the
  agent has**. It answers at temperature 0 with ≤ 1024 tokens. Its `<sql>` is executed and returned to the agent
  as SQL + result (or error), like `execute_sql`. The agent keeps all its other tools and answers as usual.
  - Adapter calls are logged separately (prompt, output and cached tokens, time).
- **Reported per arm × brief:** accuracy ± SE (paired SE vs (a)), errors by type (the Stage 0 table), turns,
  repair turns, adapter calls, output tokens (agent + adapter), p50/p95 task time, prefill tokens (agent + adapter;
  computed as prompt − cached).
- **Estimate:**
  - 6 runs × 150 tasks. From Test 3, a base arm takes ≈ 2.5 min; (d) is estimated at ≈ 5 min, for un-shared
    adapter prefill and LoRA decode.
  - Plus a 5-task smoke per arm, and ≈ 5 min for server start: ≈ 35 min wall, **≈ 0.15 node-h**.
  - `--time 1:00`, so the cap is 0.25 node-h, against the 2 node-h expert budget.
