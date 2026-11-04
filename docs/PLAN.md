# D3 plan: let the query optimizer decide which paused agents keep their KV cache

CS 5470, done **solo** by Aryan Patel (ap2568); the team has not agreed on a direction. D3 comes from Aryan's own "Idea 1" (Consumer C) in the team's *Sources of Latency* doc. Written 2026-11-04. The first milestone is **Sat Nov 7** (all three gates), the midpoint is Mon Nov 9, and the poster is Mon Dec 7.

## Status (update this first; it is the handoff between sessions)

| Item | State |
|---|---|
| Repo | github.com/KilroyHere/dbkv, cloned at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv` |
| Python env | Built in `$SCRATCH/envs/dbkv-env`: Python 3.11.7, vLLM 0.33.0, PyTorch 2.14 (CUDA 13; driver 580 is OK), DuckDB 2.0 |
| Model | Qwen3-8B in `$SCRATCH/huggingface` (16.4 GB, snapshot `b968826d`) |
| Main Claude | Remote Control session `dbkv-perlmutter`, kept alive by `setup/dbkv-claude` |
| Push from Perlmutter | Works (deploy key) |
| G1 oracle simulation | **v1 done** (job 60824732, 2 min, 0.004 node-h). **The oracle gap is about 0%:** always-keep + program FCFS is already as good as knowing each query's duration, so prediction 2a is not met. Taken at face value this is G1's kill condition. Before the Sat go/no-go: add a move-to-CPU action, refit costs from G3, and re-run (§2, 2a) |
| TPC-H data | **Done** (job 60823995, 21 s, ~0.001 node-h): `$SCRATCH/dbkv/tpch/tpch_sf1.duckdb` (268 MB, 6.0M lineitem rows) and `tpch_sf10.duckdb` (2.7 GB, 60.0M rows). SF100 not generated yet |
| G2 `EXPLAIN` calibration | Not started; TPC-H ready, so it is unblocked |
| G3 memory limit | Prediction 1a pre-registered (~32 sessions at 4k, ~16 at 8k, ~6.5 at 20k). Kill line amended to be judged at 8k and 20k (§3). Replayer `harness/replay.py` written. The first smoke job, 60824576, failed at engine start (FlashInfer lock on `$HOME`; fixed in `env.sh`); **retry 60824741 queued** (0.125 node-h). Main sweep ~1.35 node-h, not submitted |
| Continuum code | Located: github.com/Hanchenli/vllm-continuum, vLLM 0.10.2; the released code uses a fixed 2 s per-tool threshold, not the paper's Eq. 1 (→ §9a). Stony Brook repo audited (→ §9b) |

**Next:** generate TPC-H (CPU job), then G2 and G1 in parallel, then G3 on a GPU by Saturday.

## 1. The project in one paragraph

Many SQL agents share one A100-40GB. Each agent alternates between an LLM turn and a SQL query. While it waits on the query, its KV cache (about 2.9 GB for a 20K-token Qwen3-8B context) sits idle on the GPU. Above roughly 6–8 such agents, the engine has to choose, for each paused agent, whether to **keep** the cache, **move** it to CPU memory, or **drop** it. The best existing system, Continuum (ICLR 2026), keeps it for a timeout learned from that tool's past durations. That fails for SQL, because one `execute_sql` tool covers both 5 ms lookups and 30 s scans. D3 asks the database for its plan estimate (`EXPLAIN`, a few ms) before running each query. It turns that estimate into a coarse class (short, medium or long) and sends it to the engine as a hint. The engine then keeps, moves or drops the cache per class. Keeping or moving a cache never changes what the model writes, so the mechanism is lossless.

**Research question.** With SQL latency spread from milliseconds to tens of seconds, at 1.5–3× the GPU memory limit, does per-call keep/move/drop from a calibrated `EXPLAIN` class cut p95 task completion time by ≥20% compared with Continuum's per-tool timeout?

**What we measure.** The main metric is p50 and p95 task completion time. Supporting metrics are the time from a tool's return to the agent's next token, split into queueing, prefill and reload; re-prefilled tokens; and GPU KV utilization.

## 2. Pre-registered predictions

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
    - **How it is scored:** against vLLM's startup line "GPU KV cache size: N tokens", and against the session count where preemption or prefix-cache misses on resumed turns first appear. *Observed: —*
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
3. Above the limit, with millisecond-only queries, always-keep plus program-level scheduling comes within 10% of Continuum.
4. With Redshift-like query times (p50 0.1 s, p90 1.8 s, p99 26 s), per-call classes beat the per-tool timeout by 15–20% at p95.
5. `EXPLAIN` puts queries in the correct one of three classes at least 70% of the time.
6. `EXPLAIN` beats per-template history on templates it hasn't seen, but not on seen templates.

## 3. Go/no-go tests: decide before building the engine change

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

## 5. Schedule

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
| G3 memory limit | ~6 |
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

## 9. Prior art to audit (open the papers yourself)

Continuum (arXiv 2511.02230), InferCept, KVFlow, TOPAS (2608.25523), ThunderAgent, Autellix, NVIDIA Dynamo agent hints, arXiv 2601.12967, the Stony Brook project (github.com/Omkar38/agent-kv-retention), Leis et al. (cardinality errors), and Redshift short-query acceleration. For each, write a one-sentence delta in `docs/prior-art.md`.

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

## 10. Open questions for the advisor

- Bhaskar's brief centers on a persistent tool-result cache. The bridge is that a cache hit is a zero-length pause, so it is one more class for the policy. Is that enough coverage of the brief?
- Can the course grant more GPU hours if the 45-hour personal cap binds?
