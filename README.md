# dbkv: serving many SQL agents on shared GPUs without changing their answers

CS 5470 (Aryan Patel). Many tool-using SQL agents share one or a few GPUs. Every mechanism studied here changes **how agents are served, never what they answer**: a shared per-database schema brief, a gateway that admits whole tasks and orders requests by task start, and routing by database. The question: at loads near or above one GPU's capacity, how much p95 task time and throughput do these mechanisms recover at unchanged accuracy, compared with a naive deployment, and when does each lose?

**Start with [AGENTS.md](AGENTS.md).**

**Status (Nov 15): next phase, "improving model serving for data agents on one node"** ([docs/PLAN.md](docs/PLAN.md) §2j). Qwen3-32B (dense, BF16, non-thinking) served by one vLLM instance with tensor parallel 4 on a full Perlmutter GPU node (4 × A100-40GB), driving our SQL agent on DuckDB analytics data (TPC-H SF10/SF100, TPC-DS SF10). Five serving options are built one after another, A → C → B → E → D (inference stack, joint speculation, goodput gateway, task-aware eviction, EXPLAIN query scheduling), each measured as the added gain on the best system so far. Phase 0 (setup) is in progress. The midpoint pause (Nov 6) and Part C are superseded.

## Headline results (8B record, Nov 4–9)

Setup: Qwen/Qwen3-8B on 1× A100-SXM4-40GB (Perlmutter), vLLM, a minimal ReAct SQL agent on BIRD dev (1,534 questions, 11 SQLite databases).

1. **Where time goes.** In the real agent's task time, LLM decode is ~90% (89% in the explore arm) and the database is 3.6%. `results/t2_summary.md`, `results/fig_d2_time_breakdown.png`.
2. **KV memory limit.** `harness/kv_limit.py` predicted 32 / 16 / 6.5 concurrent sessions at 4k / 8k / 20k context, and the measured cliff is right there (full-hit fraction ~0.9 at the predicted N, 0.10–0.34 one step above). `results/g3_summary.md`, `results/fig_g3_limit.png`.
3. **Gateway.** At 250 tasks/min, admission + task-start priority cuts p95 by 82% (144 s vs stock ≥786 s) and gives 1.9× throughput (199 vs 105/min). It also beats the best vLLM request cap (`--max-num-seqs 64`) by p95 −67%. `results/phase2_gateway.md`, `results/a3_reqcap.md`, `results/fig_load_curve.png`.

All results and figures are indexed in [results/README.md](results/README.md); the full story is in [docs/OVERVIEW.md](docs/OVERVIEW.md).

## Layout

| Path | Contents |
|---|---|
| `harness/agent/` | The frozen ReAct SQL agent on BIRD (`run_bird.py`, `tools.py`; tag `agent-frozen-v1`) and its analysis |
| `harness/agent_duckdb/` | The agent on DuckDB (W; tag `agent-duckdb-v1`), being ported to Qwen3-32B and W3 (tag `agent-32b-v1`) |
| `harness/plancache/` | W / W2 question templates and stream generators; W3 builds on them |
| `harness/brief/` | Schema-brief generator built from the database alone, and the D2 analyses |
| `harness/gateway/` | Gateway (admission, priority, routing), open-loop load generator, mock vLLM, summarizer |
| `harness/` | G3 session replayer, KV-limit calculator, D5 overhead probe |
| `sim/` | KV simulator (G1) and `openloop*.py`, the open-loop capacity simulator for Phase 2 |
| `calib/` | EXPLAIN-vs-runtime calibration on DuckDB (G2) |
| `engine/` | Notes on the Continuum fork of vLLM 0.10.2 (cited baseline only) |
| `setup/` | `env.sh`, `perlmutter_setup.sh`, `dbkv-claude`, `dbkv-notify`, `job-nh` |
| `slurm/` | Perlmutter job scripts |
| `results/` | Small summaries and figures (`figures.py`); raw traces stay in `$SCRATCH/dbkv` |
| `docs/` | `OVERVIEW.md`, `PLAN.md` (lab notebook), `PERLMUTTER.md` (environment log), `EXPERT.md`, prior-art notes |

## Where it runs

Everything runs on Perlmutter. The repo lives at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv`; data and traces go in `$SCRATCH/dbkv/`. Heavy work runs in Slurm jobs, never on login nodes; from Nov 15, GPU jobs take a full node (1 node-h per hour). Setup: [docs/PERLMUTTER.md](docs/PERLMUTTER.md).
