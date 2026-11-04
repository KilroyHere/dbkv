# D3 plan: let the query optimizer decide which paused agents keep their KV cache

Team 19, CS 5470. Owner: Aryan Patel (ap2568). Written 2026-11-04. Midpoint is Mon Nov 9; the poster is Mon Dec 7.

## 1. The project in one paragraph

Many SQL agents share one A100-40GB. Each agent alternates between an LLM turn and a SQL query. While it waits on the query, its KV cache (about 2.9 GB for a 20K-token Qwen3-8B context) sits idle on the GPU. Above roughly 6–8 such agents, the engine has to choose, for each paused agent, whether to **keep** the cache, **move** it to CPU memory, or **drop** it. The best existing system, Continuum (ICLR 2026), keeps it for a timeout learned from that tool's past durations. That fails for SQL, because one `execute_sql` tool covers both 5 ms lookups and 30 s scans. D3 asks the database for its plan estimate (`EXPLAIN`, a few ms) before running each query. It turns that estimate into a coarse class (short, medium or long) and sends it to the engine as a hint. The engine then keeps, moves or drops the cache per class. Keeping or moving a cache never changes what the model writes, so the mechanism is lossless.

**Research question.** With SQL latency spread from milliseconds to tens of seconds, at 1.5–3× the GPU memory limit, does per-call keep/move/drop from a calibrated `EXPLAIN` class cut p95 task completion time by ≥20% compared with Continuum's per-tool timeout?

**What we measure.** The main metric is p50 and p95 task completion time. Supporting metrics are the time from a tool's return to the agent's next token, split into queueing, prefill and reload; re-prefilled tokens; and GPU KV utilization.

## 2. Pre-registered predictions

Write these on the midpoint slide before seeing results, then score them afterwards.

1. The memory limit falls at about 6–8 concurrent 20K-token Qwen3-8B agents per A100-40GB.
2. Below the limit, all policies land within 5% of each other.
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
| Repo | `/global/cfs/cdirs/m4999/team19/ap2568/dbkv` | Backed up; teammates can read it through the existing ACLs. GitHub remote later, if the team wants one |
| Data, DuckDB files, traces, model weights | `$SCRATCH/dbkv/` (`/pscratch/sd/a/ap2568/dbkv`) | Fast. Purged after 8 weeks without access, which is fine through Dec 7. Copy summaries into `results/` |
| Python environments | `/global/common/software/m4999/` if writable, else `$SCRATCH/envs/` | NERSC recommends `/global/common/software` for installs; imports from CFS are slow. Use two envs: `dbkv` (CPU tools plus a recent vLLM for G3) and `continuum` (vLLM 0.10.2 fork) |
| Editing, git, Claude Code | Login node, in the existing `team19-rc` tmux session | Light work only. No simulations, query runs or data generation |
| G1 simulator, G2 calibration, TPC-H generation | CPU compute nodes, `shared` QOS, 16–32 cores | Charged against the CPU allocation (see Section 6) |
| G3, baselines, mechanism, sweeps | GPU nodes, 1-GPU `shared` / `shared_interactive` | DuckDB runs on the 16 cores and 64 GB that come with each GPU, at no extra charge |

**What Perlmutter adds to the plan.**
- **Real long queries.** A CPU node has 128 cores and 512 GB RAM, enough to generate TPC-H SF100 once. Real queries then take tens of seconds, so injected Redshift-like delays become a cross-check, not the main source of long pauses.
- **A "remote warehouse" ablation.** Put DuckDB on a small shared CPU job and point the proxy at it over the network. The host is handed off through a file on CFS. This also frees the GPU job's 64 GB for offloaded KV caches. Keep it as an ablation: a database job running for the whole sweep would use too many CPU node-hours.

## 5. Schedule

| Dates | Work | Done when |
|---|---|---|
| **Wed Nov 4 – Thu Nov 5** | Move the repo to CFS; build both envs; download Qwen3-8B to `$SCRATCH`; locate Continuum's code and license and read its timeout rule; generate TPC-H in a CPU job; write the trace schema | `sim/` and `calib/` run in a shared CPU job |
| **Thu Nov 5 – Sat Nov 7** | G1 simulator with back-of-envelope parameters. G2 on ~1,000 queries (TPC-H templates × parameters × SF1/SF10, BIRD dev gold SQL, exploration probes). Start G3 on Perlmutter if a GPU slot is free | G1 and G2 numbers exist |
| **Sun Nov 8** | Midpoint slide: predictions next to results, plus a go/no-go call. Print by 5 pm if the midpoint is a poster | Slide or poster done |
| **Mon Nov 9** | **Midpoint.** Ask the instructor and Bhaskar one specific question: is a GPU-side mechanism driven by the database in scope for the brief? | Feedback recorded |
| **Nov 10 – 16** | Record agent traces (ReAct loop, Qwen3-8B, BIRD). Build the replayer. Get the Continuum fork running on Perlmutter and reproduce stock-vLLM and Continuum behavior. Finish G3 and refit the simulator to measured numbers | Baselines run under the replayer |
| **Nov 17 – 23** | Mechanism: proxy hint path plus a per-class policy in the fork. First p95 comparison against Continuum, then tune thresholds in the simulator | First end-to-end result |
| **Nov 24 – 30** (Thanksgiving) | Queue sweeps as batch jobs: sessions {2, 4, 8, 12, 16, 24, 32} × query-time mix {ms-only, TPC-H real, Redshift-like} × 8 policies × 3 repeats. Ablations: predictor, number of classes, smaller-KV model, context length, TP=4 vs 4 replicas | All poster plots exist |
| **Dec 1 – 6** | "When it loses" panel, final plots, poster | Poster printed |
| **Mon Dec 7** | Poster session | — |

## 6. Compute budget

The team has ~180 node-hours (45 per person). A 1-GPU shared job costs ¼ node-hour per hour, comes with 16 cores and 64 GB RAM, and is limited to 48 h. A 2-GPU job gets 128 GB at double the charge.

| Phase | Node-hours |
|---|---|
| G3 memory limit | ~6 |
| Build and debug (`shared_interactive`, 1 GPU, 4 h sessions) | ~10–20 |
| Main sweeps (~500 runs × 15–20 min) | ~30–45, less if the simulator prunes the grid |
| Ablations | ~15–25 |
| **Total** | **~60–95** |

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
- If one person runs everything, they hit the 45 node-hour cap, so spread sweep jobs across accounts.
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

## 10. Open questions for the team and advisor

- Who wrote Idea 1 in *Sources of Latency*? D3 is its Consumer C, so credit them and invite them in.
- Bhaskar's brief centers on a persistent tool-result cache. The bridge is that a cache hit is a zero-length pause, so it is one more class for the policy. Is that enough coverage of the brief?
- Should this repo live on GitHub under the team? It is local only until the team decides.
