# dbkv plan: serving many SQL agents on shared GPUs without changing their answers

*Framing since Thu Nov 5 2026, evening (Aryan): **serving many SQL agents on shared GPUs without changing their answers.***
- *Contributions:*
  1. *characterization: time anatomy, the G3 memory limit, the priority test (done);*
  2. *a shared per-database brief as a cached prefix under load;*
  3. *an agent gateway: whole-task admission from `kv_limit.py` plus task-start priority;*
  4. *multi-GPU routing by database.*
- *Out of scope: broker/DB caching, KV retention for slow queries, the expert adapter, speculative decoding, answer trimming, stateful sessions.*
- *The D2 schema-brief work below is kept as written; it becomes contribution (2)'s input.*

*(Earlier header, kept:)* **D2, schema briefs that remove SQL agents' exploration turns**

*Direction since Thu Nov 5 2026: **D2** (§1). The earlier direction, **D3** (the optimizer's estimate decides which paused agents keep their KV cache), is **closed**: G1 showed its mechanism has nothing to act on. D3's gates and tests are kept as the characterization results (§11). Every pre-registered rule and observation below is kept exactly as written; superseded parts carry a dated note.*

CS 5470, done **solo** by Aryan Patel (ap2568); the team has not agreed on a direction. D3 comes from Aryan's own "Idea 1" (Consumer C) in the team's *Sources of Latency* doc. Written 2026-11-04. The first milestone is **Sat Nov 7** (all three gates), the midpoint is Mon Nov 9, and the poster is Mon Dec 7.

## Status (update this first; it is the handoff between sessions)

| Item | State |
|---|---|
| **Framing (Nov 5 evening)** | **Serving many SQL agents on shared GPUs without changing their answers.** Contributions: (1) characterization, done; (2) shared per-DB brief as a cached prefix under load (Phase 1); (3) agent gateway with admission + priority (Phase 2); (4) multi-GPU routing by DB (Phase 3). Overnight rules are in §2f, the roadmap is §5 |
| **Final system (Nov 6, B1)** | **compact whole-DB brief + gateway "both" (admission K = 72 + task-start priority), 1 GPU; no routing.** Tag `system-frozen-v1` (`0002aae`). A3 met: "both" beats the best vLLM request cap (`--max-num-seqs 64`) by p95 −67% and 151% throughput at 250/min. P3 not met with compact (−3%) or full (−1%): routing dropped, a negative result |
| Part A (Nov 6) | A1: S3 passes under Aryan's same-job amendment. **A2/P3 NOT MET.** **A3 MET.** **A4: stock collapse ≈ 200 tasks/min;** both plateaus at 190–200/min. 1.443 GPU node-h. `results/a2_phase3.md`, `a3_reqcap.md`, `a4_collapse.md` |
| Part C | §2g pre-registered: naive vs ours × 100/170/230/300 per min × 2 reps (~0.75 node-h). **Waiting for Aryan's go** |
| Overnight Nov 5–6 | **Phase 1 done: P1 NOT MET** (compact +4.0 / +2.7 accuracy points vs explore; p95 above explore at 32 and 64), but it halves full's p95 at c = 64 (47 vs 99 s). KV accounting done. **S2 passed** on the retry after one fix (prefix-cache reset; a position-in-job drift of 5–8% was the cause of attempt 1). **Phase 2 done: P2 MET.** At 250/min, both cuts p95 by 82% (144 vs ≥ 786 s) and raises throughput to 190% of stock. Admission alone: −74%; priority alone: −45%. GPU idle 0%, overhead < 0.3 ms. **Phase 3 STOPPED: S3 failed after one fix** (router p50 +10.1% / +10.7% vs the named S2 reference; within the same job it is −5% / +7%). Aryan to decide |
| **Direction (Nov 5, superseded by the framing above)** | **D2: schema brief** (since Nov 5, Aryan). D3's mechanism is **closed** (G1 kill condition met: duration knowledge buys ≤ 6%). G1–G3, the priority test and the overnight tests are now the characterization section (§11) |
| Expert adapter (parked Nov 5) | **Negative result**, see [docs/EXPERT.md](EXPERT.md). Handing SQL writing to a BIRD LoRA adapter: accuracy +2.0 ± 2.6 points, 3.3× more invented-name errors, p50 +87%; 0.098 GPU node-h. Only the doc and `results/expert_*` were merged; `harness/expert/` stays on branch `expert` |
| D2 Stage A: brief-aware prompt (Nov 5) | **FAILED the gate; Stage B not run.** Describe calls on brief tables fall 2.17 → 0.64/0.69 per task (gate ≤ 0.3). About 55% of what remains is on tables the lexical brief shows only partially; nudged prose turns rose 0.69 → 2.52, cancelling the saving. Waiting for Aryan (§2e-pre, `results/stage_a.md`) |
| D2 step 2: fix and freeze agent | **Done, FROZEN at commit `220001e` (tag `agent-frozen-v1`).** Every later arm uses these agent files unchanged (`harness/agent/run_bird.py`, `tools.py`): Qwen3-8B non-thinking, temperature 0, max_tokens 1024, ≤ 15 turns. **Fixes:** (1) a prose reply with no tool call and no SQL gets a nudge instead of ending the task (the cause of the 28% no-SQL rate); (2) the last allowed turn forces the final SQL; (3) `describe_table` shows BIRD column descriptions, value notes and foreign keys; (4) an invented table or column returns the real names; (5) the prompt forbids guessing names. **Same 150 tasks, plain exploration, concurrency 8 (job 60872839): no-SQL 0% (was 28%), accuracy 46.0% ± 4.1 (was 36.0%), 7.4 turns per task, p50 4.1 s, p95 13.1 s.** Invented-name errors: 38 (was 109) |
| D2 step 3: prior art (`docs/prior-art-brief.md`) | **Done** (24 papers). Nearest neighbour: Sophrosyne (2605.30862), which reports tokens and accuracy only. **Open:** turns and p50/p95 latency for full vs oracle vs automatic briefs in a multi-turn agent; behaviour under concurrency and KV pressure; a shared per-database brief cached as a prefix (TableCache is single-shot only). **Baselines to add:** embedding top-k, a one-call LLM selector |
| D2 step 4: brief generator (`harness/brief/`) | **All built.** (iii) llm (60873675): table recall 91.4% / precision 90.5%, column recall 81.9% / precision 74.0%, build p50 0.46 s. **(i) compact, (ii) lexical (BM25) and oracle built for all 1,534 questions.** Mean size: (i) 2.9k chars, (ii) 0.8k, full 4.1k, oracle 0.26k. (ii) selection: table recall 95.3% (precision 70.5%), column recall 93.3% (precision 29.6%); all gold tables recalled for 90%. (iii) next. An embedding version of (ii) needs a model download (asked Aryan Nov 5). Variants (i) compact whole-DB, (ii) lexical/embedding-narrowed, (iii) cheap-model-narrowed; selection recall/precision vs gold |
| D2 step 5: full dev set (1,534) comparison, concurrency 8 | **Done: YES by the §2c rules.** Compact (i) and lexical (ii) pass R1 and R2; llm (iii) fails R1 on p95. Accuracy: explore 43.5%, full 50.4%, compact 50.7%, lexical 49.3%, llm 49.0%, oracle 58.3%. Prompt tokens per task: full 34k, compact 15k, lexical 10k, oracle 8.5k. **Caveat:** turns fall only 17–28%, because the frozen agent still calls `describe_table` (it now has descriptions the briefs lack) |
| D2 step 6: concurrency sweep 8/32/64, prefix caching on/off | **Done; rule H does NOT hold.** With caching on, lexical's p95 exceeds explore's at c = 32 (28.5 vs 25.4 s) and c = 64 (55.3 vs 45.8 s). Its per-question brief isn't shared and adds KV (58% vs 27% at c = 64). Caching off: full collapses (p95 246 s at 32, 441 s at 64), and every arm's p50 roughly doubles at c = 8. At c = 64 with caching on, full and lexical reach 100% KV. `results/d2_step6.md` |
| D2 step 7: midpoint figures (by Sun Nov 8 evening) | Not started |
| Repo | github.com/KilroyHere/dbkv, cloned at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv` |
| Python env | Built in `$SCRATCH/envs/dbkv-env`: Python 3.11.7, vLLM 0.33.0, PyTorch 2.14 (CUDA 13; driver 580 is OK), DuckDB 2.0 |
| Model | Qwen3-8B in `$SCRATCH/huggingface` (16.4 GB, snapshot `b968826d`) |
| Main Claude | Remote Control session `dbkv-perlmutter`, kept alive by `setup/dbkv-claude` |
| Push from Perlmutter | Works (deploy key) |
| G1 oracle simulation | **Done (v2b, measured costs).** The oracle gap is ≤ 5.9% at realistic pauses (Redshift 1×, SF100 measured, ms-only), with no crossover up to 30× pauses; isolated 20k cells reach 10–17%. **Kill condition met at face value**, prediction 2a not met. Sim fidelity vs real vLLM is ±14% above the limit. Offload is the real lever; released Continuum is 11–46% worse than always-keep + program FCFS at realistic pauses |
| TPC-H data | **Done** (job 60823995, 21 s, ~0.001 node-h): `$SCRATCH/dbkv/tpch/tpch_sf1.duckdb` (268 MB, 6.0M lineitem rows) and `tpch_sf10.duckdb` (2.7 GB, 60.0M rows). SF100 **done** (60824952, 20 min, 0.041 node-h; `tpch_sf100.duckdb`, 27 GiB, row counts checked). TPC-DS SF1/SF10 done (60824954, 26 s): `$SCRATCH/dbkv/tpcds/` |
| G2 `EXPLAIN` calibration | **SF100: passes both kill tests** (60826277, 0.136 node-h). With balanced classes, unseen-template ρ = 0.83 and accuracy is 68.6% vs history's 43.4%. SF10 (60825416) was ambiguous: 93.5% of its queries are short, so class accuracy can't discriminate. SF100 query times are saved as the G1 v2b pause mix (`results/g2_sf100_pauses.txt`: p50 0.39 s, p90 2.8 s, p99 14 s) |
| G3 memory limit | **Done, not killed** (60825601 + 60827431, 1.26 GPU node-h, 40GB). The pool is 139,232 tokens. Caches collapse just past the predicted limits (32/16/6.5), from ~0.9 full hits to 0.1–0.34 at +25%. Recompute + re-queue is 24–75% of p95 per-turn latency above the limit. Prediction 1a met within grid resolution (`results/g3_summary.md`) |
| Continuum code | **`$SCRATCH/envs/continuum-env` built** (60826039, precompiled 0.10.2 kernels, torch 2.8.0+cu128). Policies `fcfs`/`priority`/`continuum` import; no GPU test yet. Located: github.com/Hanchenli/vllm-continuum, vLLM 0.10.2; the released code uses a fixed 2 s per-tool threshold, not the paper's Eq. 1 (→ §9a). Stony Brook repo audited (→ §9b) |

**Overnight decision table (Nov 5–6; rules in §2f, pre-registered 21:37 PT before any job; nothing changed afterwards):**

| Test | Measured | Rule | Verdict |
|---|---|---|---|
| P1: shared compact brief under load | compact vs explore: +4.0 / +2.7 accuracy points; p95 32.0 vs 25.4 s (c = 32), 47.1 vs 45.8 s (c = 64). vs full at c = 64: p95 47 vs 99 s, KV 48% vs 69% | ≥ +5 points AND p95 ≤ explore at 32 and 64 | **NOT MET** (as predicted) |
| KV accounting | full's extra KV = more requests in flight (43 vs 25) + per-DB briefs held once; unique tokens per request ≈ explore's (1.4k); prefix duplication ≤ 2 of 300 | analysis | prediction half wrong (not per-agent), half right (duplication negligible) |
| S2: gateway vs direct | attempt 1: p50 +10.9% (cell-order drift, decode +7.6% in the second cell); after the fix (cache reset, order reversed): −4.3% / −7.3% | ±10% | **PASS after one fix** |
| P2: gateway, 250/min | both p95 144 vs ≥ 786 s (−82%), throughput 199 vs 105/min (190%); admission −74%, priority −45%; GPU idle 0%; overhead < 0.3 ms | ≥ 20% p95 cut, ≥ 95% throughput | **MET** |
| S3: router, 1 replica | p50 +10.1% then +10.7% vs the named S2 reference; within the same job −5.0% / +6.9% | ±10% vs Phase 2's direct | **FAIL after one fix → Phase 3 stopped** (Aryan to decide) |
| P3: affinity routing | not run | — | **not tested** |

Overnight GPU: 1.12 node-h (stop line 3). Plus 0.006 CPU node-h (simulator).

**Next (D2, Nov 5), in order:**
1. Docs (done, this commit).
2. Fix the agent: no-SQL rate < 5%; BIRD column descriptions; then freeze. Email when frozen.
3. `docs/prior-art-brief.md`.
4. `harness/brief/`: briefs (i)–(iii), with selection recall and precision.
5. Pre-register in §2c, then run 6 arms on all 1,534 dev questions at concurrency 8. Email when done.
6. Pre-register memory limits, then sweep 8/32/64 with prefix caching on/off. Email when done.
7. Midpoint figures by Sun evening.

**Rules for D2:**
- GPU expected ~5 node-h; **stop and notify if it passes 8**.
- `gpu&hbm40g` and `--time` on every job; log everything in `jobs.tsv`.
- **No speculative decoding** in any arm.
- Never change a pre-registered rule after seeing data.

**Overnight decision table (Nov 4–5; rules pre-registered in §2b at 21:49 PT before any data; nothing changed afterwards):**

| Test | Measured | Rule | Verdict |
|---|---|---|---|
| 1. D5 resume overhead (60839032) | engine non-prefill overhead = **1.9%** of p95 per-turn latency (mean of 4 loaded points; max 2.8%) | ≥ 10% pursue stateful sessions | **DROP** stateful sessions |
| 2a. DB share (60839247, concurrency 1) | DB = **3.6%** of task time (decode 90%) | ≥ 40% brings back broker + result caching | **DROP** broker + caching |
| 2b. D4 early stopping (60839247, concurrency 1) | **87%** (13 of 15) of tasks above p90 wrong (base wrong rate 66%) | ≥ 60% pursue, < 40% drop | **PURSUE** D4 (n = 15, caveat) |
| 2c. Also reported | exploring 53.5% of turns; repeated SQL 0.7% (within task) / 5.2% (across tasks) of DB time | n/a | n/a |
| 3. D2 schema brief (60839248 + 60839247) | (c) cuts turns 51.5% vs (a); explore share 53.6%; p50 (b) 2.48 s vs (c) 2.18 s (+13.8%) | pursue iff ≥ 30%, ≥ 25% cut, and (b) > 1.05 × (c) | **PURSUE** D2 (but (b) already gets the turn cut; the gap is prompt size; accuracy 36 / 43 / 54%) |

Overnight GPU: 0.153 node-h (stop line 3.5). BIRD agent accuracy: 34–36% plain.

**Go/no-go inputs for Sat Nov 7 (all observed by Nov 4, 7 pm; nothing in any gate or prediction changed; Aryan decides):**

| Gate | Result | Kill rule at face value |
|---|---|---|
| G1 oracle sim | Knowing each query's duration buys ≤ 6% at p95 at realistic SQL pause lengths, and there is no crossover up to 30× | **Met: kill D3's mechanism** |
| G2 `EXPLAIN` | SF100: unseen-template ρ 0.83, 3-class accuracy 68.6% vs history 43.4%. SF10 was ambiguous: 93.5% of queries are short | Not met: passes |
| G3 memory limit | Cliff at the predicted limits; recompute + re-queue is 24–75% of p95 above them | Not met: passes |

- **Taken together:** the memory problem is real (G3) and the optimizer signal works (G2), but the signal has nothing to act on (G1).
  - Per-call retention decisions don't beat program-level FCFS plus offload at realistic SQL pause lengths.
  - On real vLLM, program-level priority alone cuts p95 by 3–23% (tier-2 item 2).
- **That matches §8a outcome (b), the characterization pivot.** Outcome (a) would need a crossover at realistic pauses, and none appeared.
- **Open questions for (b):**
  - always-keep with real pinning on vLLM (the Continuum fork, `continuum-env` built);
  - offload (LMCache) measured;
  - the "Ask the Tool" counter-evidence (keep-all worse without program FCFS) tested directly.

*(Nov 4 work queue below: done, kept as a record.)*

**Next (tier 1, Nov 4):** the G3 main sweep, once the subagent's script is reviewed; the G2 SF10 run, then SF100; G1 v2 (offload, a breaker visible per policy, pause scale 1/3/10/30× plus an SF100 mix, the oracle gap plotted against pause/generation time, Continuum as its own line); a draft of §8 options (a) crossover and (b) characterization pivot before Sat.

**Tier 2 (Aryan, Nov 4), in order, whenever tier 1 is blocked on jobs:**
1. Simulator fidelity: run the sim at G3's cells and report the p95 error per cell. Flag it if the error is large.
   - **Done (Nov 4; `results/g1_fidelity.csv`; stock policy, G3-refit costs `results/g3_costs.json`, 5 seeds vs G3 reps).**
     - *Task p95:* median |error| 8%, 17 of 20 cells within 25%. **Every above-limit cell is within ±14%.** The worst cells are at light load: 8k × 4 +39%, 20k × 4 +33%, 4k × 8 +28%.
     - *Resume-TTFT p95:* the sim underestimates it below the limit by 40–85% (about 0.1 s vs 0.3–0.9 s; real per-request overheads aren't modeled). Above the limit it is within ±22%.
     - *Verdict:* not bad enough to undermine G1, which compares policies above the limit. Don't quote the sim's absolute resume latency below the limit.
   - *Refit costs (decode R² 0.945, 42 points): t0 11.6 ms, prefill 11.4k tok/s, c_dec 0.072 ms/seq, c_att 8.1e-8 s/token, KV pool 139,232. These are close to the v2a guesses except c_dec (0.2 → 0.07 ms).*
   - *G1 v2b (refit costs + SF100 pause mix) submitted as job 60832776.*
2. Real-vLLM test of G1's headline: `--scheduling-policy priority` with priority = task start, against stock, at 8k and 20k above the limit (~0.5 node-h).
   - **Done (job 60827432, 40GB, 0.22 node-h; `results/g3_priority_60827432.md`).** Program-level priority alone, with no KV pinning, beats stock vLLM.
     - p95 task time: −3 to −4% at 8k, −22 to −23% at 20k.
     - p50 task time: −8 to −35%.
     - Tasks completed: 13–70% more.
     - Resume p50: 1.6–3.1 s vs 6.9–16.9 s.
     - Full prefix hits stay near 0% for both, because vLLM priority doesn't keep a paused agent's KV. So real always-keep needs pinning (the Continuum fork). The first attempt (60825810) landed on an 80GB node and is invalid.
3. `docs/prior-art.md`: is always-keep + program FCFS already shown (Autellix, Continuum, …)? One line per paper.
   - **Done (Nov 4): partially shown.** InferCept, Continuum's ablation (Fig. 16), ThunderAgent and the Stony Brook repo each cover a piece. Nobody runs an always-keep arm or an oracle under program FCFS.
   - **Counter-evidence:** arXiv 2609.18849 finds keep-all predictors up to ~25% worse than LRU without program FCFS, and argues pre-call estimates can't know tool durations.
   - **Already taken:** 2608.30830 already reports that released Continuum is a fixed 2 s pin, and gives a ~109 s retain-vs-discard break-even on H100.
   - **Still new:** the SQL pause-length crossover under program FCFS, `EXPLAIN` as a pre-call signal, and the separation of the scheduling win from the TTL win.
4. `results/figures.py`: slide-ready G1/G2/G3 plots for Nov 9. **Draft done (Nov 4):** `fig_g1_gap_vs_ratio`, `fig_g1_policies`, `fig_g2_explain`, `fig_g3_limit` (G3 partial). Re-run once G3 and G1 v2b finish.
5. Continuum env: a CPU job building `$SCRATCH/envs/continuum-env` from vllm-continuum (vLLM 0.10.2), trying precompiled wheels first.

**Guardrails while running unattended:**
- If total project GPU spend passes **5 node-h** before Sat, stop and notify Aryan.
- Never change a gate, kill rule or prediction. Record observations only; changes wait for Aryan.
- If any gate result looks decisive either way, notify Aryan immediately.
- GPU spend (Nov 4): used 0.44 (smoke 0.069, 80GB-mislanded 20k sweep 0.207, 80GB priority test 0.165). Running or queued: 4k+8k sweep 60825601 (~0.9–1.1), 20k redo 60827431 (~0.47), priority redo 60827432 (~0.28). **Expected total ≈ 2.2 node-h (≈ 2.6 if every job hits its limit), against the 5 node-h stop line.**

## 1. The project in one paragraph (framing since Nov 5 evening)

Many tool-using SQL agents share one or a few GPUs. Our measurements show three things:
- Their time is LLM decoding over many turns. The database is 3–15% of task time.
- GPU KV memory sets a sharp concurrency limit, which `harness/kv_limit.py` predicts to within grid resolution (G3).
- Scheduling order matters: program-level priority cuts p95 by 3–23% on real vLLM.

Every mechanism we study changes **how agents are served, never what they answer**:
- **(2) a shared per-database brief** placed first in the prompt, so concurrent agents on one database reuse its cached prefix;
- **(3) a gateway** that admits whole tasks only while the KV model says they fit, and orders requests by task start;
- **(4) routing by database** across GPU replicas, so each replica's prefix cache stays warm, with a load cap against hot databases.

**Research question.** At loads near and above one GPU's capacity, how much p95 task time and throughput do these serving-side mechanisms recover, at unchanged accuracy, compared with a naive deployment (full schema, round-robin, stock scheduling)? And when does each one lose?

## 1-d2. The D2 project paragraph (Nov 5; superseded Nov 5 evening by §1, kept as written)

A SQL agent answering a question about an unfamiliar database spends its first turns exploring it: listing tables, describing them, sampling rows. In our Qwen3-8B ReAct agent on BIRD dev (Test 2, overnight Nov 4), **53.5% of turns were exploration**. Each turn costs a full LLM call, and **decoding is 90% of task time** (the database is 3.6%). Giving the agent a schema brief up front removes most of those turns:
- the full schema plus samples halves turns (6.1 → 3.1) and raises accuracy 36% → 43%;
- an oracle brief that lists only the gold SQL's tables and columns gets 54% with a third of the prompt (Test 3).

The full schema is expensive, though. It is 8.6k prompt tokens per task and has the worst p95, and prompt tokens become KV memory, which matters as concurrency rises (G3: the memory cliff is real and sharp).

**Research question.** Can a compact, automatically built schema brief, built from the database alone with no gold information, match the oracle brief's turns, median and p95 latency, and accuracy, without the full schema's prompt cost? And does that hold as concurrency rises?

**What we measure.**
- Per arm: turns per task, p50/p95 task time, accuracy (paired standard errors against the other arms on the same questions), prompt tokens.
- Selection recall and precision of each brief against the gold SQL's tables and columns.
- In the concurrency sweep (8/32/64 agents, prefix caching on/off, brief first so agents on one database share it): KV usage, preemptions, prefix-cache hits.

## 1-old. The D3 project paragraph (superseded Nov 5 by §1; kept as written)

Many SQL agents share one A100-40GB. Each agent alternates between an LLM turn and a SQL query. While it waits on the query, its KV cache (about 2.9 GB for a 20K-token Qwen3-8B context) sits idle on the GPU. Above roughly 6–8 such agents, the engine has to choose, for each paused agent, whether to **keep** the cache, **move** it to CPU memory, or **drop** it. The best existing system, Continuum (ICLR 2026), keeps it for a timeout learned from that tool's past durations. That fails for SQL, because one `execute_sql` tool covers both 5 ms lookups and 30 s scans. D3 asks the database for its plan estimate (`EXPLAIN`, a few ms) before running each query. It turns that estimate into a coarse class (short, medium or long) and sends it to the engine as a hint. The engine then keeps, moves or drops the cache per class. Keeping or moving a cache never changes what the model writes, so the mechanism is lossless.

**Research question.** With SQL latency spread from milliseconds to tens of seconds, at 1.5–3× the GPU memory limit, does per-call keep/move/drop from a calibrated `EXPLAIN` class cut p95 task completion time by ≥20% compared with Continuum's per-tool timeout?

**What we measure.** The main metric is p50 and p95 task completion time. Supporting metrics are the time from a tool's return to the agent's next token, split into queueing, prefill and reload; re-prefilled tokens; and GPU KV utilization.

## 2. Pre-registered predictions

*Note (Nov 5): predictions 1–6, 2a and §2b were registered for D3 and the overnight tests. They stay exactly as written, with their observations. D2's predictions go in §2c, written before each D2 comparison runs.*

Write these on the midpoint slide before seeing results, then score them afterwards.

1. The memory limit falls at about 6–8 concurrent 20K-token Qwen3-8B agents per A100-40GB.
1a. *(Written Nov 4, before any G3 run; computed by `harness/kv_limit.py`.)*
    - **Inputs:**
      - KV size: Qwen3-8B stores 2 × 36 layers × 8 KV heads × 128 head_dim × 2 B = **144 KiB per token**.
      - Memory budget: 0.9 × 39.39 GiB = 35.45 GiB, under vLLM `gpu_memory_utilization` 0.9.
      - Weights: 15.26 GiB.
      - Overhead (activations, CUDA graphs and non-torch memory): 1–3 GiB.
    - **KV pool:** 17.2–19.2 GiB, which is **≈ 132k tokens** (125k–140k).
    - **Memory limit at 4k context: 32 sessions** (range 30–34).
    - **Memory limit at 8k context: 16 sessions** (range 15–17).
    - **Check at 20k context:** 6.5 sessions, which is consistent with prediction 1.
    - **How it is scored:** against vLLM's startup line "GPU KV cache size: N tokens", and against the session count where preemption or prefix-cache misses on resumed turns first appear.
    - *Observed, smoke job 60824741 (1 rep, 2 min per point):*
      - *KV pool: vLLM reports **134,448 tokens**, 1.5% above the mid estimate and inside the 125k–140k range. vLLM's own split: weights + non-torch 15.44 GiB, peak activation 1.64 GiB, CUDA graphs 0.23 GiB, KV 18.46 GiB.*
      - *8k × 16 and 20k × 6 (at the predicted limit): KV usage peaks at 97% and 94%. 89–90% of resumes are full prefix hits. p95 resume TTFT is 1.1–1.8 s, against 0.12 s at 4k × 8 with no memory pressure.*
      - *20k × 10 (1.5× the limit): **0% full hits**. Resume TTFT p50 is 11.7 s and p95 14.7 s. No task completed in the 2-minute window.*
      - *Session-level limits come from the main sweep.*
    - *Observed, main sweep (jobs 60825601 4k+8k and 60827431 20k; A100-40GB, 2 reps × 24 cells, 300 s measured; `results/g3_summary.md`, `g3_table.csv`):*
      - *KV pool 139,232 tokens: +5.1% vs predicted, +3.6% vs the smoke start.*
      - *Full-hit fraction at the predicted limit: 4k × 32 = 0.94, 8k × 16 = 0.94, 20k × 6 = 0.90. One grid step above it collapses: 4k × 40 = 0.34, 8k × 20 = 0.10, 20k × 8 = 0.23.*
      - *The cliff sits **between the predicted limit and +25%** at all three contexts.*
      - *By the strict rule (≥0.95 full hits, 0 preemptions), the observed limits are one grid step below the prediction: 24 (4k), 12 (8k), 4 (20k). The true value lies between that and the predicted N.*
      - *Reading: **met to within grid resolution**, with the strict cut-off slightly conservative.*
2. Below the limit, all policies land within 5% of each other.
2a. **G1 prediction** *(written Nov 4, before the G1 grid ran).*
    - **Values:** at 1.5–3× the memory limit with Redshift-like pauses, at 8k and 20k context, the oracle beats the best per-tool policy by **≥15% at p95** task time. "Best per-tool policy" means the best of stock LRU, always-keep, released Continuum (2 s), Continuum Eq. 1, and fixed timeouts from 0.1 to 30 s. Below the limit, and with millisecond-only pauses, the gap is **<5%**. An `EXPLAIN` stand-in with log-space noise σ = 1 recovers **about half** of the gap.
    - **Where the numbers come from:** they are carried over from predictions 2–4, since the oracle must beat the per-call classes, which prediction 4 puts at 15–20%.
    - **Disclosure:** before this was written, a 1-seed, 5-minute debug grid (`--quick`) was run to check the code. Its p95s were too noisy to read, with gaps between −44% and +5% at 1 seed.
    - **Caveat:** the simulator's GPU cost parameters are back-of-envelope until G3 measures them, so G1 is re-run after G3.
    - *Observed, G1 v1 (job 60824732, 5 seeds × 20 min simulated; `results/g1_gap.csv`): **not met.***
      - *Oracle gap with Redshift-like pauses at 1.2–3× the limit: about 0% in most cells, ranging from −1.3% to +13.0%.* The only cell ≥10% is 20k × 10 sessions (13%). Per-seed p95 spread is about ±10%, so that cell is likely noise.
      - *Below the limit: within ±2%, except −6% at 20k × 4. This part matches the prediction.*
      - *Best policy above the limit: almost always **always-keep with program-level FCFS** (or `ttl:30`). Knowing each call's duration adds almost nothing on top of it.*
      - *Released Continuum (2 s) is 5–30% worse than always-keep. Stock LRU (request FCFS) is about 2× worse.*
      - *The noisy `EXPLAIN` stand-in is 8–30% **worse** than the best per-tool policy, because noise makes it drop caches it should keep.*
      - *Caveats:*
        1. *v1 has no move-to-CPU action, only keep or drop.*
        2. *Its cost parameters are guesses until G3.*
        3. *About 23% of runs hit the deadlock breaker.*
      - *Taken at face value, this meets G1's kill rule (<10% in every realistic setting). See the Status table.*
    - *Observed, G1 v2a (job 60825742, still guessed GPU costs; 33,000 runs, 5 seeds; `results/g1v2_gap.csv`, `g1v2_breaker.csv`, `g1v2_gap_vs_ratio.png`):*
      - *What v2 adds: offload for every policy, Belady (furthest-return) victims for the oracle, the breaker counted per policy, and the breaker-free `keep-ac`.*
      - *Aggregation is strict: a policy is invalid at a cell if any seed completed no task. The first, lenient aggregate averaged over surviving seeds and showed 40–56% "gaps" that were artifacts of starvation.*
      - *Oracle gap above the limit, by pause scale. Max/median gap, and cells ≥ 10% out of 13:*
        - *1×: 0.9 / 0.0, 0 of 13 (pause ÷ generation r = 0.15–0.21).*
        - *3×: 10.6 / 2.6, 1 of 13 (r = 0.42–0.81).*
        - *10×: 10.0 / 0.0, 1 of 13 (r = 1.3–4.7).*
        - *30×: 16.5 / 0.0, 1 of 13 (r = 9–19). The 16.5% cell is one seed: 206 s against 752–936 s for the other four.*
        - *ms-only: 0 / 0.*
      - *Reading: **no crossover.** There is a weak bump to about 5–10% at r ≈ 0.5–2 for 20k at high load. Prediction 2a is still not met.*
      - *Best per-tool policies are mostly offload variants (`lru+off`, short `ttl+off`). Offload, not duration knowledge, is the lever above the limit.*
      - *Deadlock breaker:*
        - *`keep` hits it in 30% of runs (cells ≥ 1.2×). `keep-ac` hits it in 0%.*
        - *At 1× pauses, `keep-ac` is within ~3% of `keep` or better, so always-keep's v1 win was not the breaker evicting for it.*
        - *At 10–30× pauses `keep-ac` is 10–40% worse, because admission control idles the GPU.*
      - *Starvation: oracle variants starve a seed in 166 of 9,600 runs. Pinning until return under strict program FCFS can block the queue head.*
      - *Released Continuum (`cont2`) vs `keep-ac`, median over cells above the limit: +13% at 1×, +54% at 3× (worse), −11% at 10× and −20% at 30× (better).*
    - *Observed, G1 v2b (job 60832776; G3-refit costs, `results/g3_costs.json`; adds the TPC-H SF100 measured pause mix; `results/g1v2b_gap.csv`, `fig_g1_gap_vs_ratio.png`):*
      - *Aggregation now also requires throughput validity: a policy counts at a cell only if it completes ≥ 50% of the best policy's tasks, because p95 over completed tasks flatters policies that finish only the fast ones. v2a was re-aggregated the same way (`results/g1v2_gap.csv`).*
      - *Oracle gap above the limit (max / median, cells ≥ 10% out of 13):*
        - *1×: 0.7 / 0.0, 0 of 13.*
        - *3×: 10.7 / 0.0, 1 of 13.*
        - *10×: 5.9 / 0.0, 0 of 13.*
        - *30×: 16.5 / 0.0, 1 of 13.*
        - ***SF100 mix: 5.9 / 0.0, 0 of 13** (r = 0.17–0.22, mean pause 1.5 s).*
        - *ms-only: 0 / 0.*
      - ***No crossover.** The only cells ≥ 10% are isolated 20k cells at 1.8–3× the limit.*
      - *`cont2` vs `keep-ac`: +11% at 1×, +46% at 3×, −11% at 10×, −20% at 30×, and +33% on the SF100 mix. Breaker: `keep` 32% of runs, `keep-ac` 0%.*
      - ***Prediction 2a not met.** At face value G1's kill rule (< 10% in every realistic setting) is met: the realistic settings are 1×, SF100 and ms-only, all with max ≤ 5.9%.*
3. Above the limit, with millisecond-only queries, always-keep plus program-level scheduling comes within 10% of Continuum.
4. With Redshift-like query times (p50 0.1 s, p90 1.8 s, p99 26 s), per-call classes beat the per-tool timeout by 15–20% at p95.
5. `EXPLAIN` puts queries in the correct one of three classes at least 70% of the time.
   - *Observed, G2 job 60825416 (TPC-H SF10 + TPC-DS SF10, 1,824 queries, 128 templates; `results/g2_sf10_summary.md`): leave-one-template-out 3-class accuracy is **92.4%**. That is nominally met, but uninformative: 93.5% of queries are "short" (<0.25 s), so always guessing short scores 93.5%.*
   - *Query times under the GPU-job caps: p50 24 ms, p90 0.18 s, p99 0.70 s, max 14 s. Only 2 of 1,824 are "long" (≥2 s).*
   - *Observed, G2 job 60826277 (TPC-H SF100, 707 queries, 29 templates; budget-cut random subset; `results/g2_sf100_summary.md`): balanced classes (308 short, 307 medium, 92 long). Leave-one-template-out accuracy is **68.6%**, just under the predicted ≥70%.*
6. `EXPLAIN` beats per-template history on templates it hasn't seen, but not on seen templates.
   - *Observed, job 60825416. The direction matches on rank and error, but not on class accuracy.*
     - *Unseen templates: `EXPLAIN` MAE is 0.40 log10 against 0.79 for history, which for an unseen template is the global median; Spearman ρ 0.82. But class accuracy is 92.4% against 93.5%.*
     - *Seen templates: history is better, MAE 0.30 vs 0.32 and accuracy 96.9% vs 94.8%.*
   - *Observed, SF100 (job 60826277): **matches prediction 6.***
     - *Unseen templates: `EXPLAIN` 68.6% vs history 43.4% accuracy; MAE 0.54 vs 1.08 log10; ρ 0.83.*
     - *Seen templates: history is slightly better, 85.0% vs 82.3%, MAE 0.45 vs 0.43.*
     - *`EXPLAIN` latency: mean 9 ms, p50 3 ms, p99 120 ms (the first call per query includes planning; a repeat call averages 2 ms).*

### 2b. Overnight decision tests: rules pre-registered Wed Nov 4 2026, 21:49 PT (commit 42d56a3), before any of their data

These were written before any Test 1–3 job ran or any BIRD data was downloaded. Do not edit them. Add observations below each rule only.

**Test 1: D5 resume overhead (stateful sessions).**
- *Measurement:* vLLM 0.33 with `--enable-per-request-metrics`. For every resumed turn (turn > 0, after warm-up), record:
  - `queue` = `queue_time_ms`;
  - `engine_ttft` = `time_to_first_token_ms` (scheduled → first token: the prefill of the tool result plus any recompute);
  - `rest` = client TTFT − `queue` − `engine_ttft` (tokenization, prefix-hash, IPC, API/HTTP, replayer client).
- *Client isolation:* on an idle server, time 20 single requests at 4k, 8k and 20k (fresh and resumed), plus a 1-token request. `client_min` = median `rest` of the 1-token request, i.e. the fixed HTTP and client cost.
- `engine_overhead` = `rest` − `client_min` + `tokenize(ctx)`.
  - `tokenize(ctx)` is the measured HF tokenizer time for the re-sent prompt as text. The replayer sends token ids, but real agents send text.
- *Loaded points:* 8k × 12, 8k × 20, 20k × 4 and 20k × 8 on an A100-40GB, Redshift-like pauses.
- *Rule:* let ratio = p95(`engine_overhead`) / p95(turn e2e) at each loaded point, and take the mean ratio over the 4 points.
  - **≥ 10%: pursue stateful sessions.**
  - **< 10%: drop.**
- *Observed (job 60839032, A100-40GB; `results/d5_summary.md`):*
  - *Ratio p95(engine_overhead) / p95(turn e2e) at the four loaded points: 20k × 4 = 2.3%, 20k × 8 = 1.4%, 8k × 12 = 2.8%, 8k × 20 = 1.0%. **Mean 1.9% → DROP stateful sessions.***
  - *Breakdown of p95 resume TTFT above the limit (8k × 20): queue 4.4 s, prefill 1.2 s, rest 0.19 s. Queue wait and recompute dominate, not per-request overhead.*
  - *Idle: `client_min` = 2.2 ms. Size-dependent `rest` is 6/10/23 ms at 4k/8k/20k. The tokenizer adds 6.6/13/59 ms.*

**Test 2: real SQL-agent traces (BIRD dev, 150 tasks, seed 0, Qwen3-8B non-thinking, temperature 0, ≤ 15 turns).**
- A *turn* is one LLM call. *Tools:* `list_tables`, `describe_table`, `sample_rows`, `execute_sql` on SQLite, with a 60 s timeout.
- *Correct:* the final SQL's result rows equal the gold SQL's as sets (BIRD execution match). The final SQL is the last ```sql``` block in the final message, else the last successful `execute_sql`. No answer, an error or a timeout counts as wrong.
- *Rule DB:* DB share = Σ tool wall time / Σ task wall time, pooled over the 150 tasks at **concurrency 1**.
  - **≥ 40%: broker + result caching come back.**
  - **< 40%: drop them.**
  - (Concurrency 8 is reported, not judged.)
- *Rule D4:* among tasks whose task latency is above the p90 at **concurrency 1**, take the share wrong.
  - **≥ 60%: pursue early stopping (D4).**
  - **< 40%: drop.**
  - 40–60%: inconclusive. (Concurrency 8 is reported, not judged.)
- *Also reported:*
  - the share of DB time from repeated queries: exact text and sqlglot-canonical, within a task and across tasks on the same DB;
  - the share of turns spent exploring: `list_tables`, `describe_table`, `sample_rows`.
- *Observed (job 60839247, A100-40GB; `results/t2_summary.md`):*
  - *Accuracy 34.0% ± 3.9 at concurrency 1 and 36.0% ± 3.9 at concurrency 8. Mean 6.1 turns per task; task time p50 2.7 s, p95 5.1 s (concurrency 1).*
  - ***Rule DB:** DB share = **3.6%** at concurrency 1 (1.1% at concurrency 8) → **DROP broker + result caching.** Decode takes 90% of task time, prefill 4%.*
  - ***Rule D4:** **87%** (13 of 15) of tasks above p90 are wrong → **PURSUE D4.** Caveats: n = 15, so the SE is about 9 points; and the overall wrong rate is 66%, so the lift from slowness is about 21 points.*
  - *Exploring: **53.5%** of turns, 64% of tool calls. DB time from repeated SQL: 0.7% within a task (exact = canonical), 5.2% across tasks on the same DB (17% at concurrency 8, where total DB time is small).*
  - *Tool errors: 71 no-such-column, 38 no-such-table, 12 syntax. Task status: 107 answered with a final SQL, 42 with no ```sql``` block (graded on their last successful query), 1 hit the turn cap.*

**Test 3: D2 pilot, schema brief (same 150 tasks, concurrency 8).**
- *Arms:*
  - (a) plain, reusing Test 2's concurrency-8 run;
  - (b) the full schema plus 3 sample values per column in the system prompt;
  - (c) an oracle brief: only the gold SQL's tables and columns, extracted with sqlglot.
- *Report per arm:* mean turns per task, p50 and p95 task time, accuracy ± standard error, mean prompt tokens per task.
- *Rule:* **pursue D2 iff** all three hold:
  1. explore share of turns in (a) ≥ 30%;
  2. mean turns (c) ≤ 0.75 × mean turns (a);
  3. p50 task time (b) > 1.05 × p50 (c).
  
  Otherwise **drop D2**. If (b) is within 5% of (c), or better, a schema brief is just a configuration.
- *Observed (jobs 60839248 for (b) and (c); (a) = 60839247 at concurrency 8; `results/t3_summary.md`):*

  | arm | turns/task | p50 / p95 task s | accuracy ± SE | prompt tokens/task |
  |---|---|---|---|---|
  | (a) plain | 6.10 | 2.91 / 5.50 | 36.0% ± 3.9 | 4,680 |
  | (b) full schema | 3.08 | 2.48 / 6.80 | 43.3% ± 4.0 | 8,632 |
  | (c) oracle brief | 2.96 | 2.18 / 5.03 | 54.0% ± 4.1 | 2,827 |

  - *Conditions: (1) explore share (a) = 53.6% ≥ 30%: yes. (2) (c) cuts turns 51.5% vs (a), so ≤ 0.75 holds: yes. (3) p50 (b) 2.48 s > 1.05 × p50 (c) = 2.28 s: yes, (b) is 13.8% slower. **→ PURSUE D2.***
  - *Caveats:*
    - *(b) already gets almost all of the turn reduction (3.08 vs 2.96). The (b)–(c) latency gap comes from prompt size (8.6k vs 2.8k tokens), not fewer turns.*
    - *(c)'s accuracy gain (+10.7 points over (b)) uses gold-SQL knowledge, so it is an upper bound on what a learned brief could reach.*
    - *(b)'s p95 is the worst of the three.*

**Budget for the night:** GPU spend stops at 3.5 node-h (expected ~2.5). Every GPU job pinned to `gpu&hbm40g`, and every job has `--time`.

### 2c. D2 step 5: pre-registered Thu Nov 5 2026, before any brief-arm agent run on the full dev set

*Do not edit; add observations below. Data seen before writing this: the 150-task plain check (46.0%, 7.4 turns); Test 3 (150 tasks, old agent); brief sizes and the (ii) selection recall/precision on all 1,534 questions. No agent run with (i), (ii) or (iii), and no full-dev-set agent run, had happened.*

**Setup.**
- Frozen agent `220001e` on all **1,534** BIRD dev questions at **concurrency 8**, one vLLM server per job, A100-40GB. Prefix caching on (vLLM default). Speculative decoding off.
- The brief goes in the system prompt after the fixed instructions, under "Database schema:".
- **Arms:**
  - **explore:** no brief.
  - **full:** every table, every column, 3 sample values (`tools.schema`).
  - **(i) compact:** `build.py --variant compact`.
  - **(ii) lexical:** BM25 over names, descriptions and samples, narrowing (i).
  - **(iii) llm:** one Qwen3-8B call per question narrows (i). Its wall time, measured at concurrency 8 in a separate pass on the same server, is added to task time.
  - **oracle:** (i)'s format narrowed to the gold SQL's tables and columns.

**Metrics** (per arm, over the 1,534 questions):
- mean turns;
- p50/p95 task time;
- accuracy, with **paired** SE for differences between arms on the same questions: sd(diff)/√n;
- mean prompt tokens per task, summed over its turns.

**Definitions.**
- *Turn-reduction retention* of arm X = (turns_explore − turns_X) / (turns_explore − turns_oracle).

**Rules** (judged on point estimates; paired SEs reported alongside):
- **R1, the brief removes exploration like the oracle.** A generated arm X ∈ {(i), (ii), (iii)} passes iff all three hold:
  - retention(X) ≥ 0.60;
  - acc_X − acc_full ≥ −2.0 points (paired);
  - p95_X ≤ p95_explore.
- **R2, without the full schema's prompt cost.** X passes iff mean prompt tokens/task of X ≤ 0.5 × full's.
- **The research question's answer (at concurrency 8) is "yes" iff at least one generated arm passes both R1 and R2.** Each arm is reported separately. With three candidates, a pass by only one arm is reported with that caveat.

**Predictions (point guesses):**

| Arm | turns | accuracy | p95 | prompt tokens/task |
|---|---|---|---|---|
| explore | 7.4 | 46% | 13 s | — |
| full | 3.5 | 50% | — | ~11k |
| oracle | 3.1 | 58% | — | — |
| (i) compact | 3.6 | 49% | — | ~7k |
| (ii) lexical | 4.0 | 47% | — | ~4k |
| (iii) llm | 3.6 | 50% | — | — (build p50 ~0.6 s) |

- **(i) passes R1 but fails R2. (iii) passes both. (ii) fails R1 on accuracy** (its column recall is 93%).
- *Observed (jobs 60873599, 60873600, 60873675; all 1,534 questions, 0.51 GPU node-h; `results/d2_step5.md`):*

  | arm | turns | p50 / p95 s | accuracy | Δ vs full (paired SE) | prompt tok/task | explore-turn share |
  |---|---|---|---|---|---|---|
  | explore | 7.45 | 4.04 / 12.51 | 43.5% | −6.9 (1.1) | 10,387 | 50.8% |
  | full | 6.15 | 4.39 / 15.55 | 50.4% | — | 34,256 | 39.8% |
  | (i) compact | 6.18 | 3.81 / 11.83 | 50.7% | +0.3 (0.9) | 15,409 | 43.5% |
  | (ii) lexical | 6.04 | 3.76 / 12.08 | 49.3% | −1.1 (1.0) | 10,146 | 40.4% |
  | (iii) llm | 5.97 | 4.16 / 13.72 | 49.0% | −1.4 (1.1) | 8,572 | 39.6% |
  | oracle | 5.34 | 3.61 / 11.26 | 58.3% | +7.9 (1.1) | 8,504 | 40.4% |

  - ***R1:*** *(i) PASS (retention 0.602, borderline). (ii) PASS (0.666). (iii) FAIL, on p95 only (13.72 s > 12.51 s; its build step adds p50 0.46 s, p95 0.87 s).*
  - ***R2:*** *all three pass.*
  - ***Answer at concurrency 8: YES** (compact, lexical).*
  - *Predictions vs observed:*
    - *Accuracy: predicted fairly well (full 50.4 vs 50; oracle 58.3 vs 58; compact 50.7 vs 49).*
    - *Turns: predicted badly (full 6.15 vs 3.5; oracle 5.34 vs 3.1).*
    - *"(ii) fails R1" was wrong: (ii) passes. "(iii) passes both" was wrong: (iii) fails R1 on p95.*
  - *Why turns barely fell: with a brief, the frozen agent still calls `describe_table` 3,000–3,900 times per arm (explore: 4,000).*
    - *Its prompt says "check names with describe_table before using them".*
    - *`describe_table` now carries BIRD's column descriptions, which no brief includes.*
    - *So every arm reduces turns by only 17–28%, against about 50% in Test 3 with the older agent. That limits what any brief can show.*
    - *Retention is measured against the oracle under the same agent, so the R1 test is internally consistent. But the absolute effect is small.*
  - *Selection quality (iii): table recall 91.4%, precision 90.5%; column recall 81.9%, precision 74.0%.*
  - *Side effect: briefs bring more runaway SQL.*
    - *60 s SQL timeouts: explore 2, full 6, oracle 9, lexical 20.*
    - *Calls over 10 s are 94% of lexical's DB time, so the DB share of task time rises from ~3% (explore) to 15% (lexical).*
    - *With a brief, the agent writes bigger joins without probing first. This feeds the p95 tail.*

### 2d. D2 step 6: concurrency sweep, pre-registered Thu Nov 5 2026 14:03 PT (commit 41f8aec), before any sweep run

*Do not edit; add observations below. Seen before writing: the step-5 results (§2c), including the per-turn prompt sizes used below.*

**Setup** (`slurm/d2_sweep.sbatch`; frozen agent `220001e`):
- **Questions:** a fixed 300-question subset of BIRD dev (seed 0).
- **Arms:** explore, full, **lexical**, oracle.
  - *Why lexical:* "best generated brief" = the step-5 R1+R2 passer with the highest turn-reduction retention: lexical 0.666 vs compact 0.602. This selection rule is stated here, after step 5.
- **Grid:** concurrency 8, 32, 64; **prefix caching on and off** (one server per setting). 4 × 3 × 2 = 24 cells.
- **Prompt layout:** the frozen agent puts the fixed instructions (~500 tokens) first, then the brief, then the question. So the full brief is a per-database prefix shared by every agent on that database. Lexical and oracle briefs are per question.
- **Recorded per cell:** turns, p50/p95 task time, accuracy, prompt tokens. Every 2 s: KV usage, running/waiting requests, prefix-cache queries/hits, preemptions.

**Predicted memory limit per arm** (`harness/kv_limit.py`: pool 139,232 tokens). Each active agent holds its current context, the step-5 mean prompt + output per turn. Agents are almost always active (DB is ~4% of time).
- **Prefix caching off:** limit = pool / context.
- **Prefix caching on:** shared tokens are stored once. That's the instructions for everyone, plus for **full** one brief per database in flight (≤ 11 DBs × mean 4,059 tokens weighted by questions ≈ 45k). So limit = (pool − shared once) / (context − shared part).

| arm | context per agent | limit, caching off | limit, caching on |
|---|---|---|---|
| explore | 1,434 | **97** | **~150** |
| full | 5,613 | **25** | **~85** |
| lexical | 1,722 | **81** | **~115** |
| oracle | 1,638 | **85** | **~125** |

**Predictions:**
1. **Caching on:** no arm reaches its limit at c ≤ 64. Preemptions ≈ 0 in every cell, and KV usage < 90% (the full arm is highest).
2. **Caching off:** **full exceeds its limit at c = 32 and c = 64.** Expect preemptions > 0, KV usage ≥ 98%, and full's p95 at c = 64 ≥ 2× its own caching-on p95. The other arms stay below their limits at c ≤ 64 (lexical and oracle are closest at 64).
3. **The cost of turning caching off at c = 8** (p50 ratio off/on): full ≥ 1.3× (every turn re-prefills ~5.6k tokens); explore, lexical and oracle ≤ 1.15×.
4. **Rule H, "does the step-5 answer hold as concurrency rises".** Holds iff, with **caching on at c = 32 and c = 64**, lexical keeps both latency parts of R1 against the same-concurrency explore and oracle cells:
   - retention ≥ 0.60;
   - p95 ≤ explore's p95.
   
   (Accuracy is not re-judged at n = 300, where its SE is about 2.9 points; it is reported.)
   - *Extra, reported:* at c = 64 with caching off, full's p95 ≥ 1.5× lexical's.

- *Observed (jobs 60876091 caching on, 60876092 caching off; 0.63 GPU node-h; `results/d2_step6.md`):*
  - *P1 (caching on: no preemptions, KV < 90%): **NOT MET.** At c = 64, full peaks at 100% KV with 3 preemptions, lexical at 100% with 1, oracle at 94%. Explore and everything at c ≤ 32 stay below. The predicted caching-on limits (~85–150 agents) were too high.*
  - *P2 (caching off: full over its limit at 32 and 64, p95 ≥ 2× caching on): **MET.** Full at 32: KV max 98%, 1 preemption, p95 246 s (5.2× caching on). At 64: p95 441 s (4.4×). No other arm preempts.*
  - *P3 (caching-off cost at c = 8: full ≥ 1.3×, others ≤ 1.15×): **NOT MET.** The p50 ratio off/on is full 3.61, explore 1.80, lexical 1.77, oracle 1.72. Turning prefix caching off nearly doubles every arm's median, because each turn re-prefills the whole conversation.*
  - ***Rule H: DOES NOT HOLD.** With caching on, lexical keeps its turn advantage (retention 0.77 at c = 32, 0.70 at c = 64) but its p95 exceeds explore's: 28.5 vs 25.4 s at c = 32, 55.3 vs 45.8 s at c = 64.*
    - *Not SQL timeouts: excluding tasks that hit one changes p95 by < 1 s.*
    - *It tracks GPU memory contention. At c = 64, lexical's mean KV is 58% vs explore's 27%. Its prefix-cache hit rate is 79% vs 85%: per-question briefs aren't shared across agents, and the brief adds per-turn context.*
    - *The oracle brief (smaller) stays below explore (40.6 s).*
    - *So the c = 8 "yes" (§2c) does not carry to c ≥ 32 for the lexical brief.*
  - *Extra: caching off at c = 64, full p95 / lexical p95 = 3.41 (≥ 1.5, as predicted).*
  - *Accuracy at n = 300 is stable across concurrency per arm (explore 46%, full 47–48%, lexical 49–50%, oracle 54–56%).*

### 2e-pre. Stage A: brief-aware prompt quick check (Nov 5; gate set by Aryan before the run; FAILED, so Stage B not run)

- **Gate:** (2) or (3) must cut `describe_table` calls on tables already in the brief to ≤ 0.3 per task, keep no-SQL < 5%, and lose ≤ 3 accuracy points vs (1).
- **Runs:** 150 questions, concurrency 8, lexical briefs (job 60879976, 0.05 GPU node-h; `results/stage_a.md`):

| run | turns | p50 / p95 s | accuracy (Δ vs (1), paired SE) | describe on brief tables/task | nudged prose turns/task | turns after 1st OK SQL | prompt tok/task |
|---|---|---|---|---|---|---|---|
| (1) frozen prompt | 5.57 | 3.88 / 13.54 | 46.0% | 2.17 | 0.69 | 1.85 | 8,918 |
| (2) brief-aware | 5.67 | 3.54 / 14.38 | 44.0% (−2.0, 2.6) | **0.64** | **2.52** | 3.44 | 9,024 |
| (3) brief-aware + descriptions (+226 brief tokens) | 4.53 | 3.16 / 10.88 | 43.3% (−2.7, 3.0) | **0.69** | 1.29 | 2.45 | 7,296 |

- **Result: FAIL.** Both cut redundant describes by ~70%, but not to ≤ 0.3. No-SQL and accuracy are within the gate.
- **What went wrong:**
  1. **About 55% of the remaining describes (53 of 96 in (2), 57 of 104 in (3)) are on tables the lexical brief shows only partially.** Lexical narrows columns, so the agent describes the table to see the rest. That is arguably legitimate, and the gate's "brief tables" counts it as redundant.
  2. **The other ~45% are on fully shown tables, mostly in turns 1–2:** a check-first habit the prompt doesn't remove.
  3. **Removing the "check with describe_table" rule made the model reply with prose plans instead of tool calls:** nudged turns per task 0.69 → 2.52 in (2). That cancels the saved turns, so (2) has no fewer turns than (1). Adding descriptions, (3), halves that effect and gives the only real turn cut (−19%) and a better p95, at −2.7 points accuracy. The text of nudged replies isn't logged, so the exact cause is not yet visible.

### 2f. Overnight Nov 5–6: serving-side rules, pre-registered Thu Nov 5 2026 21:37 PT (commit 99c0995), before any Phase 1–3 job

*Do not edit; add observations below. The simulator's capacity estimates and its predicted p95 per policy for Phase 2 will be **added below as a dated addendum before any Phase 2 GPU run**. That adds predictions only; the rules here don't change.*

*Seen before writing this: step 5 (§2c), step 6 (§2d; explore and full at c = 8/32/64 on the same 300 questions), Stage A.*

**Phase 1: shared whole-database brief under load.**
- **Setup:** the compact brief (i), the same 300 questions (seed 0), concurrency 8/32/64, prefix caching on, frozen agent `220001e` with its frozen prompt.
- **Comparison:** against step 6's explore and full cells. Those cells are the same setup and the same 300 questions, but ran in a different job, at a different time, on a different node. That's a caveat: there is no same-job control. The c = 8 compact cell can be checked for consistency against step 5's compact arm.
- **Rule P1 — pass iff both:**
  - compact accuracy ≥ explore accuracy + 5 points (unpaired cell values; explore at that c);
  - compact p95 ≤ explore p95, at **both** c = 32 and c = 64.
- **Predictions:**

  | | c = 32 | c = 64 |
  |---|---|---|
  | compact accuracy | 50.5% (explore 45.7%, so +4.8) | 50.5% (explore 46.7%, so +3.8) |
  | compact p95 | 27 s (explore 25.4 s) | 52 s (explore 45.8 s) |
  | compact KV mean | 35% | 55% |
  | compact prefix hit | 90% | 90% |

  - **Verdict predicted: P1 NOT MET** (accuracy just under +5, p95 above explore).
  - *Observed (job 60888614; `results/phase1_shared_brief.md`, `results/d2_kv_accounting.md`):*
    - *Compact accuracy 49.7% at c = 32 (Δ vs explore +4.0) and 49.3% at c = 64 (Δ +2.7).*
    - *p95 32.0 s vs explore 25.4 s at c = 32; 47.1 s vs 45.8 s at c = 64. KV mean 34% / 48%; prefix hit 90.9%.*
    - ***P1 NOT MET** (as predicted).*
    - *Against full at c = 64, compact halves p95 (47 vs 99 s), cuts KV from 69% to 48% with no preemptions, and keeps accuracy. Against explore it matches p50 but has a worse tail.*
    - *KV accounting: full's extra KV = more requests in flight + per-DB briefs held once; per-agent unique tokens equal explore's (~1.4k); prefix duplication negligible. The first half of the KV prediction was wrong, the second right.*
- **KV accounting** (analysis, no rule): why full uses 69% KV vs explore's 27% at c = 64 despite 93% prefix hits.
  - *Prediction:* most of it is per-agent tokens. Full's per-turn context is ~5.6k vs ~1.4k, and only ~4k of it is shared.
  - *Prediction:* simultaneous same-database first requests **do** duplicate the prefix (vLLM can reuse only computed blocks), but this is < 10% of full's KV at c = 64.

**Phase 2: gateway on one GPU** (explore agent, open-loop Poisson task arrivals over all 11 BIRD databases, fixed seed, 8 min measured per point).
- **Policies:**
  - **stock:** direct-equivalent, no limit, FCFS;
  - **priority:** vLLM `--scheduling-policy priority`, priority = task start;
  - **admission:** at most K active tasks, where K comes from `kv_limit.py` with the measured per-agent context; others queue at the gateway;
  - **both.**
- **Rates:** 3 arrival rates, below / at / above capacity, chosen from the simulator (addendum).
- **Self-check S2:** the gateway with no limit and no priority matches direct-to-vLLM p50 and p95 within ±10% at one load point. If it fails after one fix, stop Phase 2 and Phase 3.
  - *Observed, attempt 1 (job 60889433, 110 tasks/min, direct first then gateway, same server): direct p50 5.12 s / p95 16.64 s / 109.4 per min; gateway 5.68 / 18.29 / 109.6. p50 +10.9% → **FAIL (narrowly)**; p95 +9.9% passes.*
    - *Diagnosis: the gateway's own cost is ~1.6 ms per request (client − server time: 16.6 vs 15.0 ms) and 0.08 ms of measured proxy overhead. The gap is GPU-side: decode 20.45 vs 19.01 ms per token (+7.6%), with more requests in flight (11.8 vs 10.6), on the same tasks and output lengths. That points to cell order and carry-over on the shared server, not the gateway.*
    - *The one fix: reset vLLM's prefix cache between cells and reverse the order (gateway first). Retry is job 60890137.*
  - *Observed, attempt 2 (job 60890137, fix applied, gateway first): gateway p50 4.83 s / p95 15.76 s / 109.8 per min; direct 5.05 / 16.99 / 109.8. p50 −4.3%, p95 −7.3% → **S2 PASS.***
    - *The second cell's decode was again slower (19.23 vs 18.42 ms/token), which confirms a position-in-job drift of ~5–8%.*
    - *Phase 2 jobs run baseline then treatment at each rate (stock→admission, priority→both). So the drift works against the treatment and the 20% P2 test is conservative.*
    - *Phase 2 submitted: jobs 60891199 (FCFS server) and 60891201 (priority server), K = 77, rates 110/190/250.*
- **Rule P2 — pass iff, at the above-capacity rate, "both" has:**
  - p95 ≥ 20% lower than stock;
  - throughput (completed tasks per measured minute) ≥ 95% of stock's.
  - Also report GPU idle time under admission and the gateway overhead (ms per request).
- **Predictions:**
  - at the above-capacity rate, "both" cuts p95 by **30%** vs stock with **2%** throughput loss; priority alone cuts 15%; admission alone 20%;
  - at the below-capacity rate, all four are within ±5%;
  - gateway overhead < 2 ms per request;
  - **P2 predicted MET**, S2 predicted to pass.
  - *Observed (jobs 60891199, 60891201; `results/phase2_gateway.md`):*
    - *At 250/min: stock p95 786 s (lower bound, 237 unfinished), 105/min; priority 430 s, 134/min; admission 204 s, 185/min; **both 144 s, 199/min → p95 −82%, throughput 190% of stock. P2 MET.***
    - *Predicted −30% (my guess) and > 80% (the simulator addendum): the simulator was right.*
    - *At 190/min no policy collapsed (the real capacity is above the simulator's 190). At 110/min the policies spread ±12% by run-to-run noise ("within ±5%" not met as stated).*
    - *GPU idle under admission 0%. Gateway overhead 0.08–0.17 ms per request (p50).*

**Phase 2 addendum: simulator predictions** (added Thu Nov 5 ~22:15 PT, before any Phase 2 GPU run; rules above unchanged).
- **Tools:** `sim/openloop.py` and `openloop_rates.py`, srun job 60888767; `results/openloop_sim_summary.md`.
- **Workload:** tasks replay real explore-agent traces (step 5, frozen agent), with Poisson arrivals.
- **Cost model:** "cal" = `results/g3_costs.json` with c_dec and c_att ×2. Closed-loop check against the step-6 explore cells (p50/p95): c = 8, 4.48/13.1 vs real 4.47/12.6; c = 32, 9.3/26.9 vs 9.2/25.4; c = 64, 15.8/46.2 vs 16.9/45.8. The uncalibrated g3 costs underestimate by up to 25% at c = 64.
- **Capacity (stock):** ~**190 tasks/min**. Throughput collapses past it: waiting requests lose their cached prefixes and re-prefill.
- **Rates chosen:** **110 / 190 / 250 tasks/min** (0.6× / 1.0× / 1.3×).
- **Admission limit:** K = floor(pool / mean active-task context) = floor(139,232 / 1,802) = **77** (61 at +25% context, 103 at −25%).

**Predicted** (8-min window, mean ± sd over 5 seeds):

| rate | stock p50 / p95 / thr | priority | admission | both |
|---|---|---|---|---|
| 110 | 5.9 / 17.2 s / 111 per min | same | same | same |
| 190 | 23 / 210 s (sd 206) / 175 | 22 / 91 s / 181 | 19.7 / 51 s / 190 | 19.7 / 51 s / 190 |
| 250 | 726 / ≥ 1,208 s / 73 | 420 / 691 s / 111 | 118 / 182 s / 195 | 118 / 182 s / 195 |

- **Against the §2f guess (30% p95 cut):** the simulator predicts **> 80%** above capacity, with "both" throughput 2.7× stock. P2 is predicted met by a wide margin.
- **GPU idle under admission:** ~0 (explore pauses are ~15 ms).
- **Caveats:**
  - the at-capacity point is metastable (stock collapses in some seeds over 30 min);
  - above capacity, admission's task time is mostly queue wait and grows with the window;
  - stock p95 above capacity is a lower bound.

**Phase 3: routing on two GPUs** (only if S2 passes). Two vLLM replicas behind the gateway, compact brief, 2 arrival rates (at and above 2× single-GPU capacity), 8 min each.
- **Policies:** round-robin (per task), least-loaded (fewest active tasks), and DB-affinity with a load cap (each DB is pinned to a replica; spill to the other when the pinned replica has > cap × fair share of active tasks; cap = 1.25).
- **Self-check S3:** one replica behind the router matches Phase 2's direct numbers within ±10%.
  - *Addendum (Nov 5 ~23:05 PT, before any Phase 3 run; adds detail only):*
    - *S3 = job 60891207: one replica, explore agent (as Phase 2), 110 tasks/min, router (affinity) cell first, then a same-job direct cell. Compared with S2's direct numbers (5.05 / 16.99 s) and the same-job direct cell.*
    - *Phase 3 rates: **380 and 500 tasks/min** = 2 × the simulated single-GPU capacity (190), and ×1.3 above it. Compact brief. A cell order that alternates the policies.*
  - *Observed, S3 attempt 1 (job 60891207): router cell p50 5.56 s / p95 17.74 s / 109.9 per min. Against the named reference (S2 direct 5.05 / 16.99): **p50 +10.1% → FAIL by 0.1 pt**; p95 +4.4% passes.*
    - *Against the same-job direct cell (5.85 / 18.75): −5.0% / −5.4%. That job's direct cell was 16% slower than the S2 job's: node-to-node speed variation exceeds the ±10% tolerance. Gateway overhead 0.08 ms per request.*
    - *The one fix is a re-measurement, because the cause (node speed) isn't fixable in code: identical retry, job 60892403. The reference is unchanged. If it fails again, Phase 3 stops.*
  - *Observed, S3 attempt 2 (job 60892403): router p50 5.59 s / p95 17.59 s. Against S2 direct (5.05 / 16.99): **p50 +10.7% → FAIL again**; p95 +3.5%. Against the same-job direct (5.23 / 17.67): +6.9% / −0.5%.*
    - ***S3 failed after one fix, so Phase 3 is STOPPED for tonight (per the failure rules). P3 is not tested.***
    - *For Aryan:*
      - *the router's own overhead is 0.08 ms per request;*
      - *within-job comparisons are inside ±10% (S2 retry −4.3%; S3 −5.0% and +6.9%);*
      - *but the cross-job reference I named (S2 attempt 2's direct, from a fast node) sits ~4–16% below other nodes' direct runs (5.12, 5.23, 5.85 s).*
      - *A self-check with a same-job control would pass. Changing the criterion is Aryan's call.*
- **Rule P3 — pass iff:** affinity + cap has p95 ≥ 15% lower than round-robin at the same (above-capacity) rate.
- **Predictions:**
  - affinity + cap beats round-robin by **15%** at the above rate (borderline) and **5%** at the at-capacity rate;
  - its prefix hit rate is ≥ 5 points higher than round-robin's;
  - least-loaded sits between them;
  - **P3 predicted borderline (50/50).**

**Additions Fri Nov 6 2026, morning (Aryan's Part A/B message), written before any Part A data.**

- **A1, S3 amendment, by Aryan after seeing the S3 data.** The S3 reference becomes the **same-job direct cell**: ±10% on p50 and p95.
  - *Reason:* node-to-node speed varies up to 16%.
  - *Under it:* S3 attempt 1 is −5.0% / −5.4% and attempt 2 is +6.9% / −0.5%, so **S3 passes**. Phase 3 may run. P3 itself is unchanged.
- **A2 setup.** Phase 3 as pre-registered:
  - 2 replicas, compact brief, 380 and 500 per min, round-robin / least-loaded / affinity + cap (cap 1.25);
  - 8-min measured window (as pre-registered), 1-min warm-up, 3-min drain cap (unfinished tasks counted as unfinished);
  - within each rate, the policy order alternates.
- **A2 extra arm (added after the overnight run):** the full-schema brief, round-robin vs affinity + cap, same rates, same design, in its own 2-GPU job.
- **A2 predictions** (refined from the KV accounting; the original P3 predictions above stand):
  - *Compact:* ~920 tokens per DB × 11 ≈ 10k tokens (7% of a replica's pool). Every brief fits on both replicas, so affinity saves little KV. **Affinity vs RR p95: −5% at 380, −10% at 500, so P3 most likely NOT MET with compact.** Prefix hit: affinity +2–4 points over RR.
  - *Full:* ~4.3k tokens per DB × 11 ≈ 47k (34% of the pool) on every replica under RR, vs ~half that under affinity. That frees ~24k tokens (~17% of the pool) per replica. **Affinity vs RR p95: −15% at 380, −30% at 500; P3-style test MET with full.** Prefix hit: affinity +8 points.
  - *Least-loaded* sits between RR and affinity in both arms.
  - *Observed (jobs 60912394, 60912395; `results/a2_phase3.md`):*
    - *Compact: affinity vs RR p95 +29% at 380 (worse), -3.0% at 500; throughput +15% at 500.*
    - *Full: −2.4% at 380, -1.0% at 500; throughput +9–10%.*
    - ***P3 NOT MET with either brief.*** *Every cell was above 2-GPU capacity (no admission in Phase 3), so p95 is queue- and drain-dominated. The full-arm KV prediction was wrong.*
    - *Not within ±5 points of the threshold, so no borderline repeat.*
- **A3, request-cap baseline (rule pre-registered here).** At 250 per min, in one job: stock vLLM with `--max-num-seqs` 32 and 64 (no gateway, direct) vs "both" (K = 77). Order: reqcap64 → both → reqcap32. 1-min warm-up, 5-min window, 3-min drain cap. Prefix-cache hits reported.
  - **Rule A3:** "both" p95 ≥ 15% lower than the best request-cap setting's p95, **and** "both" throughput ≥ 95% of the best request-cap setting's. "Best" = the lower p95 of the two.
  - **Prediction:** a request cap limits *running requests*, not *tasks*. Tasks keep piling up between turns and lose their cached prefixes.
    - reqcap64: p95 ~350 s, ~140 per min;
    - reqcap32: p95 ~300 s, ~150 per min, prefix hit ~60%;
    - both: p95 ~150 s, ~195 per min, prefix hit ~86%.
    - **A3 predicted MET** (p95 ~ −50%).
  - *Observed (job 60912396; `results/a3_reqcap.md`): reqcap64 p95 306 s (lower bound), 130/min, hit 65%; reqcap32 341 s, 118/min; **both 101 s, 197/min, hit 86% → −67% p95, 151% throughput. A3 MET.***
- **A4, collapse point (reported, no rule).** Stock and both at 210 and 230 per min, one job, order stock210 → both210 → both230 → stock230. Same window settings.
  - **Prediction:** stock keeps up at 210 (~207 per min) and falls behind at 230 (~170 per min, prefix hit < 70%), so its collapse point is ~220 per min. Both stays ~200–210 per min at both rates.
  - *Observed (job 60912397; `results/a4_collapse.md`):*
    - *Stock: 176/min at 210 (0.84 of offered, p95 107 s) and 148/min at 230 (p95 ≥ 248 s, prefix hit 70%). With Phase 2's 188/min at 190, **stock's collapse point ≈ 200 per min** (predicted ~220).*
    - *Both: 189/min at 210 and 200/min at 230 (p95 52 / 69 s, prefix hit 86%).*
- **B1 decision table (Aryan, written before Part A data), applied after Part A:**
  - *A3 met:* "both" (task-level admission + priority) is the gateway in the final system.
  - *A3 not met:* keep "both", but add the best request-cap as a required baseline everywhere, and state in Status that the gateway's edge is setting the limit automatically.
  - *P3 met with compact:* final system = compact + both + affinity routing.
  - *P3 met only with full:* final system = compact + both (no routing); routing gets its own "when it pays off" panel with the full schema.
  - *Neither:* routing dropped and reported as a negative result; the 4-GPU block becomes TP=4 vs 4 replicas only.
- **Part A budget:** expected ~1.2 GPU node-h; stop and email at 1.5.
- **B1 outcome (applied Fri Nov 6 after Part A):**
  - **A3 met → the gateway is "both"** (task-level admission + task-start priority).
  - **P3 met with neither brief → routing dropped,** reported as a negative result; the 4-GPU block becomes TP=4 vs 4 replicas only.
  - **Final system = compact whole-DB brief + "both" on one GPU.** Frozen as tag `system-frozen-v1` (`0002aae`): gateway files at that commit, agent `agent-frozen-v1`, briefs sha256-pinned in `$DBKV_DATA/frozen/system-v1`.
  - **K = 72 for compact** = floor(139,232 / 1,924), where 1,924 is the peak KV per active task in Phase 1 compact at c = 64 (job 60888614: peak 88% KV at 64 tasks, no preemptions). It follows the same "pool / per-task context" rule that gave K = 77 for explore.
- **Part A spend:** 1.443 GPU node-h (stop line 1.5).


**Failure handling.**
- A failed P1, P2 or P3 is a result, recorded honestly, and the night continues.
- Stop only on: a self-check failing after one fix (that phase only; Phase 3 needs S2), budget (**3 GPU node-h overnight**), or an unfixable crash.

### 2g. Part C: slim full run, naive vs ours (pre-registered Fri Nov 6 2026 ~10:20 PT, before any Part C job)

*Do not edit; add observations below. Seen before writing: all of Part A (A2, A3, A4) and Phases 1–2.*

**Systems** (both run from exported tagged files via `slurm/fullrun.sbatch`):
- **naive** = full-schema brief + stock vLLM (FCFS), agents talk directly to vLLM. No routing (routing was dropped).
- **ours** = the final system: compact brief + gateway "both" (admission K = 72 + task-start priority) on a priority-scheduled vLLM.
- Same frozen agent (`agent-frozen-v1`), same seeded task stream (BIRD dev over all 11 DBs), same arrival times at each rate.

**Rates:** **100, 170, 230, 300 tasks/min**, about 0.5×, 0.85×, 1.15× and 1.5× of A4's collapse point (~200/min for stock with the explore agent). The same absolute rates for both systems.

**Cell:** 1-min warm-up, 5-min measured window, 3-min drain cap. Unfinished tasks count as unfinished (in p95 as their elapsed time; in accuracy as wrong).

**Jobs:** 2 reps, on separate jobs (and so, normally, separate nodes; nodes recorded). Within each job both systems run as blocks, with the block order reversed between reps:
- rep 1: naive 100 → 170 → 230 → 300, then ours 100 → 170 → 230 → 300;
- rep 2: ours block first, then naive.

Each job restarts vLLM once (FCFS ↔ priority). No borderline repeats: A3 (−67% vs 15%) and P3 (−3% vs 15%) are both far from their thresholds. No ablations, no Continuum runs.

**Rules** (judged on the mean over the 2 reps; ranges reported):
- **H1:** ours throughput ≥ 1.5× naive's at 300/min.
- **H2:** ours p95 ≤ naive p95 × 1.10 at **each** of the below-collapse rates, 100 and 170/min.
- **H3:** ours accuracy ≥ naive accuracy − 2 points.
  - Paired by task over tasks arriving in the measured window: same seed, so the same task sequence; unfinished counts as wrong. Pooled over all 4 rates and both reps.
  - Also reported: accuracy over tasks that finished in both systems.

**Predictions** (per 1 GPU, mean over reps):

| rate | naive throughput / p95 | ours throughput / p95 |
|---|---|---|
| 100 | ~75/min / ~300 s (already over capacity) | ~99/min / ~15 s |
| 170 | ~75 / ~400 s | ~165 / ~45 s |
| 230 | ~70 / ~420 s | ~185 / ~110 s |
| 300 | ~65 / ~430 s | ~185 / ~230 s |

- Naive's capacity estimate: full on 2 GPUs managed 149–163/min, so ~75–80 per GPU.
- **H1 MET** (~2.8×), **H2 MET** (ours far lower), **H3 MET**: ours ~+5 points, because naive leaves many unfinished. Over tasks finished by both, ours − naive ≈ +1 ± 2 points.

**Cost:** 2 jobs × (8 cells × ~10 min + 2 server starts) ≈ 2 × 1.5 h → **~0.75 GPU node-h** (cap 1.1 at `--time 2:15`); stop and email at 1.5. **Not submitted until Aryan's "go".**

## 3. Go/no-go tests: decide before building the engine change

*Superseded by D2 on Nov 5. G1–G3 are complete; their outcomes are in the Status table and §11. Kept as written.*

| Gate | Question | Where | Kill D3 (or its database signal) if |
|---|---|---|---|
| **G1. Oracle simulation** | If every query's duration were known exactly, how much faster would agents finish than with Continuum's timeout? | `sim/`, CPU | Perfect knowledge beats Continuum's best timeout by <10% at p95 in every realistic setting. Then no predictor can help. |
| **G2. `EXPLAIN` calibration** | Can the optimizer separate short, medium and long queries before running them? | `calib/`, CPU (DuckDB) | Spearman ρ < 0.5, or it does no better than per-template history on unseen templates. This kills only the database signal; Section 8 gives the fallback. |
| **G3. Memory limit** | At how many agents does the KV cache run out, and how much p95 time is lost beyond that? | `harness/` replayer on stock vLLM, GPU (~6 node-hours) | No limit below 32 sessions, or recompute plus re-queueing stays under 10% of p95 per-turn latency |

**G3 sweep design (Nov 4, not yet submitted).**
- **Engine:** stock vLLM 0.33 from `dbkv-env`, with `gpu_memory_utilization` 0.9, prefix caching on and everything else default.
- **Replayer:** a synthetic `harness/` replayer. G3 needs no database, so its pauses are synthetic.
- **Sessions:** each session first fills its context to C tokens. It then loops through turns: a pause, then about 300 new input tokens (the tool result), then 150 output tokens.
- **Pauses:** sampled from the Redshift-like mix (p50 0.1 s, p90 1.8 s, p99 26 s).
- **Session counts:** chosen around the predicted limit N\*, from 0.25× to 3× N\*.

| Context | Predicted N\* | Session counts |
|---|---|---|
| 4k | 32 | 8, 16, 24, 32, 40, 48, 64, 96 |
| 8k | 16 | 4, 8, 12, 16, 20, 24, 32, 48 |
| 20k | 6.5 | 2, 4, 6, 8, 10, 12, 16, 20 |

- **Run length:** 24 points × 2 repeats. Each run is about 1 min of warm-up prefill plus 5 min of measurement. Prefix caches are reset between points, and the server starts once per job.
- **Recorded:**
  - From the replayer: time from tool return to first token (p50, p95), and task time.
  - From `/metrics`: KV usage, prefix-cache hits, preemptions.
  - Re-prefilled tokens.
- **Budget** (revised Nov 4, after adding the 20k row):
  - Smoke test (job 60824741, a retry of 60824576; 1 GPU `shared`, 30 min): 0.125 node-h. It covers 4k:8, 8k:16, 20k:6 and 20k:10, records vLLM's real KV token count, and exercises the 20k path and an above-limit point.
  - Main sweep: 48 runs × ~6.5 min (60 s warm-up, 300 s measured, about 30 s drain) ≈ 5.2 h, plus about 10 min for server start ≈ 5.4 h ≈ **1.35 node-h**, with `--time 7:00` (cap 1.75). It may be split into a 4k+8k job (~0.9) and a 20k job (~0.45).
  - **Total about 1.5 node-h (at most 1.9), compared with the ~6 budgeted.**
- **Amendment, Nov 4, before any G3 data, because the 4k prediction sits on the line.** G3's kill line, "no limit below 32 sessions", is judged at **8k and 20k context**, not at 4k. That is because 4k's predicted limit (≈32, prediction 1a) falls right on the line, so the 4k result would trip it by construction. The 4k row is still measured and reported in full. The 20k row was added so the line can be judged at the project's premise context.

**G3 result (Nov 4, observed; the rule is unchanged): not killed.**
- (a) A limit exists well below 32 sessions. First failure: N = 16 at 8k and N = 6 at 20k (and N = 32 at 4k, reported only).
- (b) Recompute + re-queue share of p95 per-turn latency, (resume TTFT p95(N) − baseline) / turn e2e p95(N): 0.24–0.70 at 8k for N ≥ 20, and 0.41–0.75 at 20k for N ≥ 8. Both are far above the 10% line.
- Above the limit, turn e2e p95 inflates 2.3–8.5× relative to the at-limit point, and from 2× the limit (4k × 96, 8k × 48, 20k × 16 and above) no task completes inside the 5-minute window.

Order: G1 first, because it bounds everything. G2 can run in parallel. G3 also supplies the measured prefill, reload and capacity numbers that replace the simulator's back-of-envelope parameters.

## 4. Implementation decisions (given ~4.5 weeks)

| Decision | Choice | Why | Rejected alternative |
|---|---|---|---|
| Engine | Fork **Continuum** (vLLM 0.10.2) and replace its duration predictor with a hint-driven per-class policy | Keep-with-timeout, program-level scheduling and the baseline already exist, so our delta stays small | Porting to SGLang (the plan in Idea 1), or rebuilding on the latest vLLM. Either would take weeks we don't have |
| Policy design | **Simulator first**, engine second | Policies can be iterated on CPU in minutes. GPU runs only validate selected points | Tuning in the engine directly, which burns node-hours and is slow |
| Database | **DuckDB** in-process (TPC-H SF1/SF10/SF30 via the `tpch` extension; BIRD dev attached from SQLite). Postgres via podman-hpc is optional, for cost-unit estimates | No container needed; runs on a laptop and inside a GPU job | SQLite, because its `EXPLAIN QUERY PLAN` has no cost or row estimates |
| Model | Qwen3-8B, non-thinking mode (144 KiB/token of KV). Qwen2.5-7B (56 KiB/token) as an ablation | Puts the memory limit at single-digit concurrency on 40 GB | Larger models, which leave too little KV room on one GPU |
| Workload | **Replay**: token counts and turn structure recorded from a real ReAct agent on BIRD, with SQL pauses from (a) executing agent-like SQL on TPC-H in DuckDB and (b) sampling the Redshift and Snowflake latency distributions | The mechanism is lossless, so we need no accuracy runs. Replay is cheap and repeatable | Live agents solving tasks in every run, which is slow, noisy and costs node-hours |
| Hint channel | The proxy runs `EXPLAIN`, maps it to a class and attaches it to the agent's request metadata. The engine reads it when the request ends in a tool call | Keeps database code out of the engine | The engine calling the database itself |
| Baselines | Stock vLLM (LRU prefix cache); always-keep with program-level FCFS; Continuum; CPU offload (LMCache, if it runs on 0.10.2); per-template history predictor; oracle | Covers the strongest config-only fix and the state of the art | — |

Environment: use a separate virtual environment for the Continuum fork. Pin every version in `requirements*.txt`.

## 4a. Where everything runs: all on Perlmutter

| What | Where | Notes |
|---|---|---|
| Repo | `/global/cfs/cdirs/m4999/team19/ap2568/dbkv` | Backed up. Remote: github.com/KilroyHere/dbkv |
| Data, DuckDB files, traces, model weights | `$SCRATCH/dbkv/` (`/pscratch/sd/a/ap2568/dbkv`) | Fast. Purged after 8 weeks without access, which is fine through Dec 7. Copy summaries into `results/` |
| Python environments | `$SCRATCH/envs/dbkv-env` (built), and later `$SCRATCH/envs/continuum-env` | `/global/common/software/m4999` is shared by the whole class and was full. Imports from CFS are slow |
| Editing, git, Claude Code | Login node, in tmux session `dbkv` (Remote Control `dbkv-perlmutter`, kept alive by `setup/dbkv-claude`) | Light work only. No simulations, query runs or data generation |
| G1 simulator, G2 calibration, TPC-H generation | CPU compute nodes, `shared` QOS, 16–32 cores | Charged against the CPU allocation (see Section 6) |
| G3, baselines, mechanism, sweeps | GPU nodes, 1-GPU `shared` / `shared_interactive` | DuckDB runs inside the GPU job, using the 16 cores and 64 GB that come with each GPU at no extra charge. It is **capped at `SET memory_limit='16GB'` and `SET threads=8`**, so it never squeezes vLLM's CPU offload space or its CPU-side work (tokenizer, scheduler, proxy). Every DuckDB connection opened in a GPU job sets both caps |

**CPU nodes vs GPU jobs.** Standalone heavy work that needs no GPU, such as TPC-H generation, G2 calibration and the G1 simulator, runs as its own CPU-node job. A database that serves a GPU run stays inside that GPU job, with the caps above.

**What Perlmutter adds to the plan.**
- **Real long queries.** A CPU node has 128 cores and 512 GB RAM, enough to generate TPC-H SF100 once. Real queries then take tens of seconds, so injected Redshift-like delays become a cross-check, not the main source of long pauses.
- **A "remote warehouse" ablation.** Put DuckDB on a small shared CPU job and point the proxy at it over the network. The host is handed off through a file on CFS. This also frees the GPU job's 64 GB for offloaded KV caches. Keep it as an ablation: a database job running for the whole sweep would use too many CPU node-hours.

## 5. Roadmap (Nov 6, Aryan; replaces the old schedule)

Do NOT start any block without pre-registered rules and Aryan's approval of that block.

| Dates | Work | GPU node-h |
|---|---|---|
| Nov 7–8 | Aryan reviews the overnight results; midpoint slide; team doc update | — |
| Nov 9 | Midpoint. Ask the instructor whether a serving layer for agent workloads fits the scope | — |
| Nov 6–7 (added) | **Part C slim full run** (§2g), after Aryan's go: naive vs ours, 4 rates × 2 reps | ~0.75 |
| After Part C (updated Nov 6) | **4-GPU block: TP=4 vs 4 replicas first** (routing was dropped, so no routing layouts); the second model only if time allows | — |
| Nov 10–16 | 3 repeats of every poster point, with error bars; full load curves (6–8 rates); **headline comparison**: naive deployment (full schema, round-robin, stock scheduling) vs combined (shared brief + gateway + affinity routing) on p95, throughput and accuracy; Continuum fork as an external baseline | ~5 |
| Nov 17–23 | Full 4-GPU node: 4 replicas vs TP=4 vs 2× TP=2; skewed DB popularity (Zipf) to test the load cap; a second model (e.g. Qwen3-14B, TP=2) to check the KV model predicts its limit (needs Aryan's download approval) | ~6–8 |
| Nov 24–30 | When it loses: gateway overhead at light load; the explore agent under routing; long tool waits (admission idling); admission limit from the KV model vs the best hand-tuned limit; simulator vs real fidelity | ~2 |
| Dec 1–6 | Poster (problem → time anatomy → 3 mechanisms → headline → scaling → when it loses → what didn't work); repo README with one script per figure | — |

- **If time runs short:** drop the second model first, then the 4-GPU layouts. Keep the repeats, the headline comparison and when-it-loses.
- **Budget:** the roadmap totals ~13–15 GPU node-h. **Stop and ask Aryan at 20 cumulative GPU node-h counted from Nov 6.**

## 5-old. Schedule (superseded Nov 6 by the roadmap above; kept as written)

| Dates | Work | Done when |
|---|---|---|
| **Wed Nov 4** | Perlmutter setup: repo, env, model download, the always-on Claude session (done or in progress). Generate TPC-H SF1/SF10 in a CPU job, with SF100 overnight | Setup works end to end |
| **Thu Nov 5** | G2: `EXPLAIN` vs. runtime on ~1,000 queries (TPC-H templates × parameters, BIRD dev gold SQL, exploration probes), against per-template history on unseen templates. Locate Continuum's code and read its timeout rule | G2 scatter and accuracy table |
| **Thu Nov 5 – Fri Nov 6** | G1 simulator: drop, always-keep, Continuum-style timeout, perfect knowledge, and `EXPLAIN` classes using G2's real errors, over ms-only, TPC-H and Redshift-like query times | p95 vs. sessions for each policy; the oracle gap |
| **Fri Nov 6 – Sat Nov 7** | G3: synthetic replayer on stock vLLM, 2–32 sessions (~6 node-hours). Feed the measured prefill, reload and capacity numbers back into the simulator | Memory limit and time lost past it |
| **Sat Nov 7** | Go/no-go call, written into Status | Decision |
| **Sun Nov 8** | Midpoint slide: predictions next to results, plus a go/no-go call. Print by 5 pm if the midpoint is a poster | Slide or poster done |
| **Mon Nov 9** | **Midpoint.** Ask the instructor and Bhaskar one specific question: is a GPU-side mechanism driven by the database in scope for the brief? | Feedback recorded |
| **Nov 10 – 16** | Record agent traces (ReAct loop, Qwen3-8B, BIRD). Build the replayer. Get the Continuum fork running on Perlmutter and reproduce stock-vLLM and Continuum behavior. Finish G3 and refit the simulator to measured numbers | Baselines run under the replayer |
| **Nov 17 – 23** | Mechanism: proxy hint path plus a per-class policy in the fork. First p95 comparison against Continuum, then tune thresholds in the simulator | First end-to-end result |
| **Nov 24 – 30** (Thanksgiving) | Queue sweeps as batch jobs: sessions {2, 4, 8, 12, 16, 24, 32} × query-time mix {ms-only, TPC-H real, Redshift-like} × 8 policies × 3 repeats. Ablations: predictor, number of classes, smaller-KV model, context length, TP=4 vs 4 replicas | All poster plots exist |
| **Dec 1 – 6** | "When it loses" panel, final plots, poster | Poster printed |
| **Mon Dec 7** | Poster session | — |

## 6. Compute budget

This is a solo project, so the budget is Aryan's per-user cap: **45 GPU node-hours, about 37 left** (7.7 used as of Nov 3). A 1-GPU shared job costs ¼ node-hour per hour, comes with 16 cores and 64 GB RAM, and is limited to 48 h. A 2-GPU job gets 128 GB at double the charge.

| Phase | Node-hours |
|---|---|
| G3 memory limit | **Done, not killed** (60825601 + 60827431, 1.26 GPU node-h, 40GB). The pool is 139,232 tokens. Caches collapse just past the predicted limits (32/16/6.5), from ~0.9 full hits to 0.1–0.34 at +25%. Recompute + re-queue is 24–75% of p95 per-turn latency above the limit. Prediction 1a met within grid resolution (`results/g3_summary.md`) |
| Build and debug (`shared_interactive`, 1 GPU, 4 h sessions) | ~10–20 |
| Main sweeps (~500 runs × 15–20 min) | ~30–45, less if the simulator prunes the grid |
| Ablations | ~15–25 |
| **Total if run as first planned** | **~60–95, over budget** |

**Solo budget (~37):** G3 ~6, build and debug ~10, a pruned sweep ~15 (the simulator chooses which points to run on the GPU), ablations ~5. Drop the 4-GPU variant and the second model unless budget remains. If the cap becomes binding, ask the instructor whether more hours are available.

**CPU node-hours.** On Nov 3, `iris` showed a **CPU cap of 10 node-hours per user** on m4999, so CPU time is not unlimited; check `iris` again. Shared CPU jobs are charged by the fraction of the node used, so the CPU work stays small:

| CPU work | Estimate |
|---|---|
| TPC-H SF1/SF10/SF100 generation (once) | ~0.5–1 node-hour |
| G2 calibration (~1,000 queries × 3 runs + `EXPLAIN`, 32 cores) | ~0.5 |
| G1 and simulator grids (32 cores) | ~0.5–1 |
| Remote-database ablation | ~1 |
| **Total** | **~2.5–3.5 of 10** |

The database inside GPU jobs costs nothing extra, which is why it is the default.

Constraints:
- Host RAM limits CPU-offload runs. In a 1-GPU job, about 20 sessions fit (13 offloaded caches ≈ 38 GB, plus DuckDB). Bigger runs need a 2-GPU job.
- Never leave GPU jobs running unattended.

## 7. What the poster will claim

*Superseded Nov 6. Poster order: problem → time anatomy → 3 mechanisms (shared brief, gateway, routing) → headline (naive vs combined) → scaling → when it loses → what didn't work (D3 KV retention, D5, the broker, the expert adapter, brief-aware prompting). Earlier versions below are kept as written.*

*Superseded Nov 5. The D2 poster:*
1. *Where SQL-agent task time goes: decode 90%, DB 3.6%, exploration 53.5% of turns. Plus the memory cliff and program FCFS (characterization, §11).*
2. *Schema briefs: explore vs full schema vs generated briefs vs oracle, on turns, p50/p95 and accuracy.*
3. *What happens to each arm as concurrency rises: prompt size → KV memory → limit, with and without shared-prefix caching.*

*The D3 version below is kept as written.*

1. A measured anatomy: where SQL-agent task time goes on an A100-40GB, and the memory limit.
2. The state of the art's failure: per-tool history can't separate fast and slow SQL. This is the oracle gap.
3. The mechanism: the optimizer estimate as a coarse class recovers Z% of that gap and beats template history on unseen queries.
4. When it loses: below the memory limit, with uniform query times, and when estimates are bad.
5. Open traces, the replayer and the simulator.

## 8. Fallbacks, decided now

| If… | Then… |
|---|---|
| G1 fails (oracle gap <10%) | Stop the mechanism. The poster becomes the memory-pressure anatomy plus a negative result, and we join another RQ's direction |
| G1 passes, G2 fails | The predictor becomes the problem: template history, or learned plan features (but note the Stony Brook course project nearby) |
| G3 finds no limit below 32 sessions | D3 is dead on this hardware. Report the anatomy and switch |
| The Continuum fork won't run by Nov 16 | Evaluate policies in the simulator, calibrated against measured stock-vLLM runs. Implement only one policy in the engine, or none, and say so on the poster |
| Behind schedule on Nov 23 | Drop Postgres, TP=4 and the second model. Keep the three query-time mixes and the oracle |

### 8b. Decision (Thu Nov 5, Aryan)

The decision was made early, after the overnight tests. **D3's mechanism is closed. The new direction is D2, schema briefs.** D5 (stateful sessions) and the broker/result cache were dropped by their overnight rules. D4 (early stopping) passed its rule but is not the main direction. §8a's outcome (b), characterization, is kept as §11.

### 8a. Draft for the Sat Nov 7 decision (written Nov 4, before G1 v2 results; Aryan decides)

G1 v1 found the oracle gap ≈ 0% at today's Redshift-like pause lengths. G1 v2 sweeps pause length (1×, 3×, 10×, 30× and an SF100 mix) and plots the gap against *r = mean pause ÷ mean generation time per turn*. The decision turns on whether a crossover exists.

**(a) A crossover exists at realistic pause lengths, so D3 narrows to that regime.**
- **Condition:** the oracle gap reaches ≥10% at p95 for some r\* that real SQL workloads reach: SF100 query times, or Redshift's slow tail (p90 1.8 s, p99 26 s). It must hold under G3-refitted costs, and with the breaker-free `keep-ac` and offload variants included among the per-tool policies.
- **RQ becomes:** "for SQL agents whose query time is comparable to or longer than generation time (r ≥ r\*), does a per-call `EXPLAIN` class beat program-level FCFS + always-keep?"
- **Plan changes:**
  - The main workload becomes the long-pause regime: SF100, and the Redshift tail at scale ≥ r\*.
  - G2 is judged on whether `EXPLAIN` separates calls around the pause length that matters, not on generic 0.25 s / 2 s classes.
  - The engine work shrinks to a per-call pin/offload hint on top of program FCFS. Continuum's per-tool timeout stays the baseline.
- **Poster:** (1) where SQL-agent time goes and where the memory limit is (G3); (2) the r\* crossover plot; (3) the `EXPLAIN` hint recovering part of the gap above r\*; (4) released Continuum underperforming always-keep, as its own panel.
- **Risk:** if `EXPLAIN` is noisy (the G1 v1 noisy stand-in lost 8–30%), even (a) can fail at the mechanism stage. The noisy-oracle rows at σ = 0.5 and 1 bound how good G2 must be.

**(b) No crossover, so pivot to characterization: when program-level FCFS is enough, and when it isn't.**
- **Condition:** the gap stays <10% across r, contexts and loads, or crosses only at r far beyond realistic SQL. Then D3's mechanism is unnecessary on this hardware.
- **RQ becomes:** "for multi-turn SQL agents on one GPU, which serving choices (scheduling order, retention, offload) set p95 task time, and where does each stop helping?"
- **Plan changes:**
  - Drop the engine fork and the `EXPLAIN` hint path.
  - Measure on real vLLM: stock vs program-priority (`--scheduling-policy priority`, tier-2 item 2), with and without CPU offload, across the G3 grid and pause scales.
  - The simulator, once checked against G3 (tier-2 item 1), extends the measurements to the regions not run on the GPU.
  - G2 becomes a side result: how well `EXPLAIN` predicts SQL time, and whether it beats template history on unseen templates.
- **Poster:** (1) the memory-limit anatomy (G3); (2) program FCFS vs request FCFS (stock), measured on real vLLM; (3) released Continuum vs always-keep, likely its own finding; (4) the gap-vs-r plot showing where duration knowledge would start to matter; (5) the `EXPLAIN`-calibration result.
- **Prior-art check needed first** (tier-2 item 3): whether Autellix, Continuum or others already show that always-keep + program FCFS is enough. If they do, (b) is a confirmation on SQL agents plus the Continuum-vs-keep finding, which is weaker but honest.
- **Budget:** (b) needs less GPU than (a), about 3–5 node-h of measured runs and no engine debugging.

**Inputs still needed on Sat:** G1 v2 with G3 costs, the G3 sweep summary, G2 at SF10/SF100/TPC-DS, the sim-vs-G3 fidelity error, and the prior-art lines.

## 9. Prior art to audit (open the papers yourself)

Continuum (arXiv 2511.02230), InferCept, KVFlow, TOPAS (2608.25523), ThunderAgent, Autellix, NVIDIA Dynamo agent hints, arXiv 2601.12967, the Stony Brook project (github.com/Omkar38/agent-kv-retention), Leis et al. (cardinality errors), and Redshift short-query acceleration. For each, write a one-sentence delta in `docs/prior-art.md`.

### 9c. Cache-aware routing and agent admission (Nov 6, for Phase 3; `docs/prior-art-routing.md`)

- **Already shown:** prefix- and cache-aware routing beats round-robin or random by large factors.
  - Preble: 1.5–14.5× mean latency, 2–10× p99.
  - SGLang's cache-aware router: 1.9× throughput, hit rate 20% → 75%.
  - llm-d: ~170× p90 TTFT vs random near saturation.
- **Affinity plus a load check is standard,** so **"DB affinity with a load cap" is not new as a mechanism.** Examples: Preble's balance threshold, SGLang's absolute/relative imbalance switch, Dynamo's busy thresholds, SMetric's SLO check.
- **Open:** whole-task admission plus task-start priority, combined with affinity routing, evaluated for *online multi-turn agents*.
  - CONCUR does agent-level admission, but on one engine and for offline batches.
  - Dynamo ships a ThunderAgent admission plugin without published evaluation.
  - A per-database brief as the affinity key is untested.
- **Baseline to add in the roadmap's headline comparison:** SGLang's cache-aware policy, reimplemented in our gateway with its defaults (cache_threshold 0.3, balance_abs 64, balance_rel 1.5), next to round-robin and least-loaded. Not added to tonight's pre-registered P3 arms.

### 9a. Continuum: code located (Nov 4)

- **Paper:** "Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live", by Li, He, Mang, Zhang, Mao, Chen, Zhou, Zhang, Cheung, Gonzalez and Stoica. arXiv 2511.02230, v1 Nov 4 2025, with a v2. **The venue is unconfirmed.** Neither arXiv nor Semantic Scholar names one, so §1's "ICLR 2026" needs checking before it goes on the poster.
- **Code:** https://github.com/Hanchenli/vllm-continuum, linked from the paper. It is Apache-2.0, a standalone repo rather than a GitHub fork, with 9 commits; the last code change was Jan 2026 ("fix dp bug").
- **vLLM base: 0.10.2.** The paper uses that stable release for its baselines, plus LMCache 0.3.7 for CPU offload. The repo pins `torch==2.8.0`, which fits 0.10.2. This matches §4's plan for a separate `continuum-env`.
- **How the timeout is chosen in the paper (§4.1–4.2, Eq. 1):** τ* = argmax_τ P(τ,f)·Benefit − Cost(τ). Here P(τ,f) is the empirical probability, from that tool's past durations, that a call to tool f returns within τ. Benefit is the re-prefill or reload cost avoided plus the queueing cost; Cost is the memory held for τ. So the timeout depends on the tool, never on the individual call. That per-tool rule is exactly the weakness D3 targets.
- **What the released code does instead:** it is much simpler, and its README says it ships "without the estimation in the paper". `vllm/v1/core/estimate_with_func.py`, `ToolCallEstimator.set_up_pin`, uses a fixed `FIXED_THRESHOLD_CONTINUUM = 2.0` s (checked). If a tool's running-average duration is over 2 s, the cache is not pinned; otherwise it is pinned for 2 s. Tools are identified by the first word of the bash command. The rule is called from `_free_blocks` in `vllm/v1/core/sched/scheduler.py` and enabled with `--scheduling-policy continuum`. The scheduling is program-level FCFS, per `job_id`.
- **What this means for D3:**
  1. The baseline must be stated precisely. We should compare against both the released fixed-2-s rule and a faithful version of the paper's Eq. 1, implemented in the simulator and ideally in the fork.
  2. The fork's tool key, the first bash word, would put every `execute_sql` call into one bucket. That works in our favour, but we should say so explicitly.
  3. The hook point for our per-class hint is `set_up_pin`.

### 9b. Stony Brook: github.com/Omkar38/agent-kv-retention (Nov 4)

- **What it is:** the CSE 542 / AMS 560 Fall 2026 project. Created Sep 12, last pushed Nov 3, no licence.
- **Approach:** a ski-rental framing of the keep-or-evict choice. The cost model is C(τ,T) = c·min(T,τ) + B·1[T>τ], with break-even at B/c. The policy uses λ-interpolated, learning-augmented TTLs (Purohit et al.). A gradient-boosted-tree predictor estimates P(T ≥ b) from tool identity, argument size, context length, turn index and session history.
- **Data and engine:** TraceLab coding-agent traces (Claude Code and Codex, about 357k pauses). It is **simulator only** (`src/sim.py`); a vLLM/SGLang + LMCache prototype is listed only as a stretch goal.
- **Findings:** any retention policy beats immediate eviction by 6–15×. Under load, always-retain + LRU wins. Prediction helped only after session-history features were added.
- **Overlap with D3:** they share the problem and also position against Continuum's per-tool distribution. They differ in three ways: they have **no SQL and no `EXPLAIN` or plan features**, their workload is coding agents, and they have no real engine. Their finding that always-retain + LRU wins under load supports keeping our "always-keep + program FCFS" baseline (prediction 3). Cite their ski-rental cost model as related work. Section 8's fallback to a learned predictor would overlap with them, so prefer template history there.

## 11. Characterization results (D3 phase, closed Nov 5)

These measurements stand on their own and feed the D2 poster's anatomy panel. Details are in the Status rows, §2, §2b, §3 and `results/`.

| Result | Evidence |
|---|---|
| The KV memory cliff for Qwen3-8B on an A100-40GB sits at the predicted limit (≈ 32 / 16 / 6.5 agents at 4k / 8k / 20k). Past it, cache hits fall from ~0.9 to 0.1–0.34 and resume latency goes from 0.1 s to over 10 s | G3, `results/g3_summary.md` |
| Knowing each SQL call's duration buys ≤ 6% at realistic pause lengths; there is no crossover up to 30× | G1 v2b, `results/g1v2b_gap.csv` |
| Program-level priority alone cuts p95 by 3–23% on real vLLM | `results/g3_priority_60827432.md` |
| Released Continuum is 11–46% worse than always-keep + program FCFS at realistic pauses | G1 v2b |
| `EXPLAIN` predicts SQL time: SF100 unseen-template ρ 0.83, accuracy 68.6% vs 43.4% | G2, `results/g2_sf100_summary.md` |
| Resume overhead outside prefill is 1.9% of p95 per-turn latency | Test 1, `results/d5_summary.md` |
| Real BIRD agent: decode 90%, DB 3.6%, explore 53.5% of turns, 87% of slow tasks wrong | Test 2, `results/t2_summary.md` |
| A schema brief halves turns; the oracle brief reaches 54% vs 36% plain | Test 3, `results/t3_summary.md` |

## 10. Open questions for the advisor

- Bhaskar's brief centers on a persistent tool-result cache. The bridge is that a cache hit is a zero-length pause, so it is one more class for the policy. Is that enough coverage of the brief?
- Can the course grant more GPU hours if the 45-hour personal cap binds?
