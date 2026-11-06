# dbkv overview

A one-read guide to the project (read it right after [AGENTS.md](../AGENTS.md)). The detailed record is [PLAN.md](PLAN.md), and its **Status** table is the handoff point between sessions.

## 1. The question and the answer so far

**Framing (since Nov 5 evening):** "Serving many SQL agents on shared GPUs without changing their answers." The mechanisms change how agents are served, never what they answer.

**Research question:** at loads near or above one GPU's capacity, how much p95 task time and throughput do serving-side mechanisms recover, at unchanged accuracy, compared with a naive deployment? And when does each mechanism lose?

**Answer so far:** task-level admission plus task-start priority in a small gateway keeps one GPU near its ceiling past the point where stock vLLM collapses (p95 −82%, 1.9× throughput at 250 tasks/min). A compact schema brief gives about +7 accuracy points at half the full schema's tokens. DB-affinity routing did not help (a negative result).

**Final system** (frozen as git tag `system-frozen-v1` = `0002aae`): compact whole-DB brief + gateway "both" (admission K = 72 + task-start priority) on 1 GPU, with no routing. The agent is frozen as tag `agent-frozen-v1` = commit `220001e`.

**State:** the project was paused at its midpoint on Nov 6. Part C, the final naive-vs-ours run, is pre-registered (PLAN §2g) but has not been run. To resume, Aryan replies "go" to the §2g matrix. No GPU jobs have run since Nov 6. See §5 below.

## 2. Setup

- **Model:** Qwen/Qwen3-8B, bf16, non-thinking mode, temperature 0. Its KV cache costs 144 KiB per token.
- **GPU:** 1× NVIDIA A100-SXM4-40GB on NERSC Perlmutter (always `--constraint=gpu&hbm40g`). The KV pool holds 139,232 tokens at `gpu_memory_utilization` 0.9 (vLLM-reported; one early start reported 134,448).
- **Serving:** vLLM 0.33.0 in `$SCRATCH/envs/dbkv-env` (Python 3.11, PyTorch 2.14, DuckDB 2.0). A Continuum fork (vLLM 0.10.2) is built in `$SCRATCH/envs/continuum-env` but was never run in experiments; it is a cited baseline only.
- **Agent:** a minimal ReAct SQL agent, [harness/agent/run_bird.py](../harness/agent/run_bird.py) plus `tools.py`. Its tools are `list_tables`, `describe_table` (with BIRD column descriptions and foreign keys), `sample_rows` and `execute_sql` (SQLite, 60 s timeout). It gets at most 15 turns and uses native tool calling through vLLM's hermes parser.
- **Benchmark:** BIRD dev, 1,534 questions over 11 SQLite databases. A task is correct when its result rows (as a set) match the gold SQL's.
- **Other databases:** TPC-H SF1/10/100 and TPC-DS SF1/10 in DuckDB, used only for G2.
- **Load tools:** [harness/replay.py](../harness/replay.py) replays synthetic sessions (G3). An open-loop load generator plus the gateway in [harness/gateway/](../harness/gateway/) drive Phases 2–3 and Part A.

## 3. Findings

### 3.1 Where the time goes
In a real agent's task time, LLM decode is 78–90% (89% for the explore arm). The database is 3.6% (Test 2), rising to about 15% when briefs cause runaway SQL. The explore agent spends 53.5% of its turns exploring the schema.
Results: [t2_summary.md](../results/t2_summary.md), [d2_step5.md](../results/d2_step5.md). Figure: [fig_d2_time_breakdown.png](../results/fig_d2_time_breakdown.png).

### 3.2 The KV memory limit
[harness/kv_limit.py](../harness/kv_limit.py) predicted that 32 / 16 / 6.5 concurrent sessions fit at 4k / 8k / 20k context. The measured cliff is right there: the full-hit fraction is about 0.9 at the predicted N and 0.10–0.34 one step above.
Result: [g3_summary.md](../results/g3_summary.md). Figure: [fig_g3_limit.png](../results/fig_g3_limit.png).

**Priority test:** program-level (task-start) priority on real vLLM cut p95 by 3–23%.
Result: [g3_priority_60827432.md](../results/g3_priority_60827432.md). Figure: [fig_priority_test.png](../results/fig_priority_test.png).

### 3.3 Schema briefs
A *brief* is a schema summary placed in the agent's prompt, so the agent doesn't have to explore the schema.

**Accuracy vs tokens** (D2 step 5, all 1,534 questions, concurrency 8):

| arm | accuracy | prompt tokens/task |
|---|---|---|
| explore | 43.5% | — |
| full | 50.4% | 34k |
| compact | 50.7% | 15k |
| lexical | 49.3% | 10k |
| llm | 49.0% | 8.6k |
| oracle | 58.3% | 8.5k |

Result: [d2_step5.md](../results/d2_step5.md). Figures: [fig_d2_arms.png](../results/fig_d2_arms.png), [fig_d2_acc_vs_tokens.png](../results/fig_d2_acc_vs_tokens.png).

**Under load** (step 6 and Phase 1, 300 questions): the full schema's p95 doubles at 64 agents (99 s vs explore's 46 s). Compact matches explore's p50 but has a worse tail, so P1 was not met. Turning prefix caching off doubles every median.
Results: [d2_step6.md](../results/d2_step6.md), [phase1_shared_brief.md](../results/phase1_shared_brief.md). Figure: [fig_d2_sweep.png](../results/fig_d2_sweep.png).

**KV accounting:** full's extra KV comes from more requests in flight plus per-DB briefs held once. Per-agent tokens are about the same as explore's, and prefix duplication is negligible.
Result: [d2_kv_accounting.md](../results/d2_kv_accounting.md).

### 3.4 The gateway
The gateway sits between agents and vLLM. It admits at most K whole tasks at once and tags each request with its task's start time as a priority. Phase 2 and A3 use the explore agent, so K = 77; the frozen final system uses the compact brief, so K = 72.

**Why tasks, not requests.** An agent task is a chain of ~6–7 LLM requests with short tool pauses between them. Between turns, the task's conversation (its KV prefix) sits in vLLM's prefix cache, ready for the next turn. Under overload:
- **Stock vLLM, or a request cap** (`--max-num-seqs`), lets every arrived task keep issuing turns. So hundreds of half-finished tasks interleave. Each one's cached prefix is evicted by the others' before its next turn (prefix hit falls from 86% to 48–65%). Every resumed turn then re-prefills its whole conversation, so the GPU spends its time on recomputation and throughput collapses.
- **Task-level admission** lets only K tasks be in flight at a time, K being what fits in KV memory, and makes the rest wait at the gateway before their first turn. The admitted tasks keep their prefixes cached (hit 86%) and finish quickly. Task-start priority additionally finishes older tasks first.
- So the queue moves out of the GPU, where it destroys cache locality, into the gateway, where waiting is free (A3: 197 vs 130 tasks/min; `results/a3_reqcap.md`).

- **Phase 2** (explore agent, Poisson arrivals, 250 tasks/min, 8-min window): "both" p95 144 s vs stock ≥ 786 s ("≥": a lower bound, because 237 stock tasks were still unfinished at the drain cap) (−82%); throughput 199 vs 105 tasks/min (1.9×). Admission alone gives −74%, priority alone −45%. Gateway overhead is under 0.3 ms per request, and the GPU is never idle (0%).
  Result: [phase2_gateway.md](../results/phase2_gateway.md). Figure: [fig_phase2_gateway.png](../results/fig_phase2_gateway.png).
- **Load curve and collapse point (A4):** stock throughput falls below the arrival rate between 190 and 210 tasks/min (about 200/min). The gateway plateaus at about 190–200/min.
  Result: [a4_collapse.md](../results/a4_collapse.md). Figure: [fig_load_curve.png](../results/fig_load_curve.png).
- **vs a vLLM request cap (A3,** 250/min, same job): "both" p95 101 s vs `--max-num-seqs 64` 306 s (−67%); throughput 197 vs 130 per min (151% *of* the cap's, i.e. +51%). A3's "both" p95 (101 s) is lower than Phase 2's (144 s) because A3 used a 5-min window and a 3-min drain cap, against Phase 2's 8-min window, and ran on a different node. Over-capacity p95 grows with window length, so compare numbers only within one job.
  Result: [a3_reqcap.md](../results/a3_reqcap.md). Figure: [fig_a3_reqcap.png](../results/fig_a3_reqcap.png).
- **Simulator:** [sim/openloop.py](../sim/openloop.py) predicted a capacity of about 190/min and a p95 cut above 80%.
  Result: [openloop_sim_summary.md](../results/openloop_sim_summary.md).

### 3.5 Routing (negative)
DB-affinity routing with a load cap was compared with round-robin on 2 replicas. Compact gained only −3% p95 at 500/min (and was 29% worse at 380/min); full gained −1%. P3 was not met, so routing was dropped from the final system.
Result: [a2_phase3.md](../results/a2_phase3.md) (no figure).

## 4. Ruled out

- **D3, EXPLAIN-informed KV retention (the original direction):** G1's oracle simulation showed that knowing each SQL call's duration buys ≤ 6% p95 at realistic pause lengths, with no crossover up to 30× ([g1v2b_gap.csv](../results/g1v2b_gap.csv), [fig_g1_gap_vs_ratio.png](../results/fig_g1_gap_vs_ratio.png), [fig_g1_policies.png](../results/fig_g1_policies.png)). G2 showed EXPLAIN does predict SQL time (SF100 unseen-template ρ 0.83, accuracy 68.6% vs 43.4%; [g2_sf100_summary.md](../results/g2_sf100_summary.md), [fig_g2_explain.png](../results/fig_g2_explain.png)), but there was nothing for it to act on.
- **D5, stateful sessions:** per-request overhead outside prefill is only 1.9% of p95 turn latency ([d5_summary.md](../results/d5_summary.md)).
- **Broker / DB result caching:** the DB is 3.6% of task time, and repeated SQL is 0.7% (within a task) or 5.2% (across tasks) of DB time ([t2_summary.md](../results/t2_summary.md)).
- **Expert adapter** (a BIRD LoRA writes the SQL): accuracy +2.0 ± 2.6 points, 3.3× more invented names, p50 +87% ([EXPERT.md](EXPERT.md), [expert_stage1.md](../results/expert_stage1.md)).
- **Brief-aware prompt (Stage A):** `describe_table` calls on brief tables fell 2.17 → 0.64 per task, but the gate needed ≤ 0.3, and nudged prose turns rose 0.69 → 2.52 ([stage_a.md](../results/stage_a.md)).
- **Released Continuum** (cited baseline only): 11–46% worse than always-keep + program FCFS at realistic pauses (G1 v2b; PLAN §11).

## 5. Paused work and how to resume

**Part C** (PLAN §2g, pre-registered Nov 6 10:01 PT, not run):
- **Systems:** *naive* = full-schema brief + stock vLLM (FCFS), agents talk directly to vLLM. *ours* = the final system (compact brief + gateway "both", K = 72, on a priority-scheduled vLLM). Same frozen agent, same seeded task stream.
- **Rates:** 100, 170, 230 and 300 tasks/min (about 0.5×, 0.85×, 1.15× and 1.5× of the collapse point). 2 reps, block order reversed between reps. Script: `slurm/fullrun.sbatch`.
- **Rules:** H1 ours throughput ≥ 1.5× naive's at 300/min; H2 ours p95 ≤ naive's × 1.10 at 100 and 170/min; H3 ours accuracy ≥ naive's − 2 points. Predictions are written in §2g; do not edit them.
- **Cost:** about 0.75 GPU node-h (cap 1.1 at `--time 2:15`).
- **Scope note:** all gateway numbers above use the explore agent (K = 77). The frozen final system (compact brief, K = 72) has not yet been measured under load; that is what Part C does.
- **To resume:** Aryan replies "go" to the §2g matrix, in the Claude session on Perlmutter (Remote Control `dbkv-perlmutter`) or by email; the session then records it in PLAN Status. Only then submit the 2 jobs, log them in `$SCRATCH/dbkv/logs/jobs.tsv`, and add observed numbers under §2g.

**After Part C,** follow the roadmap in PLAN §5: a 4-GPU block (TP=4 vs 4 replicas), repeats with error bars and full load curves, a skewed-popularity test and a second model, "when it loses" tests, then the poster. Every block needs pre-registered rules and Aryan's approval. Stop and ask at 20 cumulative GPU node-h counted from Nov 6.

## 6. Glossary

| Label | Plain words | Where its result is |
|---|---|---|
| D1 | SQL-aware speculative decoding. Considered Nov 4, not pursued (speculative decoding is out of scope; off in every arm) | — |
| D2 | Schema-brief direction (Nov 5) | §3.3; [d2_step5.md](../results/d2_step5.md) |
| D3 | Original direction: keep/offload/drop an agent's KV cache using EXPLAIN's time estimate. Closed by G1 | §4; PLAN §1-old |
| D4 | Early stopping of hopeless agent tasks. Test 2's rule said pursue; it was not pursued | [t2_summary.md](../results/t2_summary.md) |
| D5 | Stateful sessions (dropped) | [d5_summary.md](../results/d5_summary.md) |
| G1 | Gate 1: oracle simulation of KV policies ([sim/kvsim.py](../sim/kvsim.py)) | [g1v2b_gap.csv](../results/g1v2b_gap.csv) |
| G2 | Gate 2: does EXPLAIN predict SQL time? ([calib/](../calib/)) | [g2_sf100_summary.md](../results/g2_sf100_summary.md) |
| G3 | Gate 3: KV memory limit on real vLLM (via `harness/replay.py`) | [g3_summary.md](../results/g3_summary.md) |
| T1–T3, "Test 1–3" | Overnight Nov 4 decision tests: Test 1 = D5 resume overhead; Test 2 = real BIRD agent traces (DB share, D4); Test 3 = schema-brief pilot (D2). Rules in PLAN §2b | [d5_summary.md](../results/d5_summary.md), [t2_summary.md](../results/t2_summary.md), [t3_summary.md](../results/t3_summary.md) |
| Stage A | Nov 5 brief-aware prompt check (PLAN §2e-pre). Failed; Stage B (full rerun) not run | [stage_a.md](../results/stage_a.md) |
| Step 1–7 | D2's work steps (Nov 5): 1 docs; 2 fix and freeze the agent; 3 prior art; 4 brief generator; 5 full-dev brief comparison (§2c); 6 concurrency sweep (§2d); 7 midpoint figures (done Nov 6, `results/figures.py`) | [d2_step5.md](../results/d2_step5.md), [d2_step6.md](../results/d2_step6.md) |
| Phase 1–3 | Overnight Nov 5–6 serving tests (§2f): 1 shared brief under load; 2 gateway on 1 GPU; 3 routing on 2 GPUs | [phase1_shared_brief.md](../results/phase1_shared_brief.md), [phase2_gateway.md](../results/phase2_gateway.md), [a2_phase3.md](../results/a2_phase3.md) |
| P1–P3 | Pass/fail rules of Phases 1–3 (PLAN §2f). **P1:** compact brief ≥ +5 accuracy points over explore AND p95 ≤ explore's at 32 and 64 agents (not met). **P2:** at the above-capacity rate, "both" cuts p95 ≥ 20% vs stock with ≥ 95% of stock's throughput (met). **P3:** affinity routing p95 ≥ 15% lower than round-robin (not met) | same as Phases |
| S2 / S3 | Self-checks that the gateway (S2) and router (S3) don't distort latency vs going direct to vLLM. S2 passed after one fix; S3 passed under amendment A1 | PLAN Status, §2f |
| A1–A4 | Part A (Nov 6): A1 S3 same-job amendment; A2 Phase 3 run (+ full-schema arm); A3 request-cap baseline (met); A4 collapse point (~200/min) | [a2_phase3.md](../results/a2_phase3.md), [a3_reqcap.md](../results/a3_reqcap.md), [a4_collapse.md](../results/a4_collapse.md) |
| B1–B3 | B1 decision table choosing the final system; B2 freeze; B3 writing §2g | PLAN Status |
| H1–H3 | Part C rules: H1 throughput ≥ 1.5× naive at 300/min; H2 p95 ≤ naive + 10% below collapse; H3 accuracy ≥ naive − 2 points. Not run | PLAN §2g |
| R1 / R2 | D2 step-5 rules: R1 a brief removes exploration like the oracle; R2 without the full schema's prompt cost | PLAN §2c; [d2_step5.md](../results/d2_step5.md) |
| rule H | D2 step-6 rule: does the step-5 answer hold as concurrency rises? (It did not) | PLAN §2d; [d2_step6.md](../results/d2_step6.md) |
| explore | Arm: no brief; the agent explores the schema itself | §3.3 |
| full | Arm: full schema + 3 sample values | §3.3 |
| compact | Arm: whole-DB compact brief (columns, types, keys, joins, 2 samples) | §3.3 |
| lexical | Arm: compact narrowed by BM25 match to the question | §3.3 |
| llm | Arm: compact narrowed by one Qwen3-8B call | §3.3 |
| oracle | Arm: only the gold SQL's tables and columns (uses gold; upper bound) | §3.3 |
| stock | Policy: vLLM FCFS, no gateway policy | §3.4 |
| priority | Policy: vLLM `--scheduling-policy priority` with priority = task start time | §3.2, §3.4 |
| admission | Policy: gateway admits at most K whole tasks | §3.4 |
| both | Policy: admission + priority | §3.4 |
| round_robin / least_loaded / affinity | Routing policies over replicas; affinity routes by DB with a load cap of 1.25 | §3.5 |
| reqcap32 / reqcap64 | Stock vLLM with `--max-num-seqs` 32 / 64 | [a3_reqcap.md](../results/a3_reqcap.md) |
| K | Admission limit in tasks = floor(KV pool / mean per-task KV): 77 for explore, 72 for compact | §3.4 |
| c | Number of concurrent agents in closed-loop runs. (Rates, in tasks/min, are open-loop Poisson arrival rates) | §3.3 |
| naive / ours | Part C systems: naive = full schema + stock vLLM; ours = final system (compact + both) | PLAN §2g |
| node-h | NERSC node-hours (a 1-GPU shared job costs ¼ node-h per hour) | `$SCRATCH/dbkv/logs/jobs.tsv` |
| `agent-frozen-v1` | Git tag for the frozen agent, commit `220001e` | PLAN Status |
| `system-frozen-v1` | Git tag for the frozen final system, `0002aae` (includes the briefs' sha256) | PLAN Status |

## 7. Where things live

Code, Slurm job scripts (`slurm/`) and small summaries (`results/*.md|json|csv|png`) are in this repo. Raw data, traces, run outputs and logs are in Aryan's `$SCRATCH` (`/pscratch/sd/a/ap2568/dbkv`: `runs/`, `bird/`, `tpch/`, `tpcds/`, `briefs/`, `frozen/system-v1/`, `logs/jobs.tsv`). Perlmutter scratch is per-user, so teammates can't read it; model weights are in `$SCRATCH/huggingface` and environments in `$SCRATCH/envs/`. See [results/README.md](../results/README.md) for what each result file holds, [REPRODUCE.md](REPRODUCE.md) for how to rerun things, and [PERLMUTTER.md](PERLMUTTER.md) for the environment.
