# AGENTS.md: start here (any coding agent: Claude, Codex, Cursor)

dbkv is Aryan Patel's CS 5470 project, done solo, on NERSC Perlmutter.

## Reading order

1. **AGENTS.md** (this file).
2. **[docs/OVERVIEW.md](docs/OVERVIEW.md)**: the project, the setup, the findings and the glossary.
3. **[results/README.md](results/README.md)**: every result file and figure, with what it shows.
4. Only then, **the one section of [docs/PLAN.md](docs/PLAN.md) you need** (its Status table, §2g for Part C, §5 for the roadmap).

**Do not read PLAN.md top to bottom.** It is a lab notebook: the history of every direction and every pre-registration, kept as written. Superseded sections are still in it.

## Current state

1. **Framing:** serving many SQL agents on shared GPUs without changing their answers. Mechanisms change how agents are served, never what they answer.
2. **Where time goes:** in the real agent's task time, LLM decode is 78–90% (89% in the explore arm) and the database is 3.6% (`results/t2_summary.md`, `results/d2_step5.md`).
3. **KV memory limit:** `harness/kv_limit.py` predicted 32 / 16 / 6.5 concurrent sessions at 4k / 8k / 20k context, and the measured cliff is right there (`results/g3_summary.md`).
4. **Gateway:** at 250 tasks/min, admission + task-start priority ("both") cuts p95 by 82% (144 s vs stock ≥786 s) and gives 1.9× throughput (199 vs 105/min). It beats the best vLLM request cap (`--max-num-seqs 64`) by p95 −67% (`results/phase2_gateway.md`, `results/a3_reqcap.md`).
5. **Paused at midpoint (Nov 6).** Part C (naive vs ours, full run) is pre-registered in PLAN §2g but not run. It resumes when Aryan replies "go" to the §2g matrix.

## Rules

- **Heavy work runs only in Slurm jobs, never on the login node.** Heavy work that doesn't need a GPU goes on CPU nodes (`--constraint=cpu`, `shared` QOS, 16–32 cores). Job scripts live in `slurm/` and start with `source setup/env.sh`.
- **No GPU jobs run while the project is paused.**
- **Every GPU job uses `#SBATCH --constraint=gpu&hbm40g`.** Plain `gpu` can land on an A100-80GB, whose ~3× larger KV pool invalidates every memory result (job 60825603, Nov 4).
- **Every job gets a `--time` limit.** Never leave a GPU job unattended; check `squeue -u $USER` before ending a session.
- **Log every job in `$SCRATCH/dbkv/logs/jobs.tsv`:** one row per job (date, job id, purpose, partition, estimated node-h). When it ends, fill in that row's actual node-h and end state from `sacct -j <id>` or `setup/job-nh <id>`. Don't add a second row. A job missing from `squeue` has not necessarily finished.
- **Budget:** check GPU budget with `iris` before any sweep. A 1-GPU `shared` job costs ¼ node-h per hour. The CPU cap is 10 node-h per user.
- **Pre-register before running.** Write the rules and predictions into PLAN.md before any data exists. Never edit them afterwards; add observed numbers next to them.
- **Prefer same-job controls.** Nodes vary by up to 16% in speed, so compare arms inside one job where possible.
- **Frozen tags:** `agent-frozen-v1` (commit `220001e`) and `system-frozen-v1` (`0002aae`). Experiment jobs run files exported from the tag, not the working tree.
- **Where things go:** code in this repo (CFS); data, traces, run outputs and logs in `$SCRATCH/dbkv`; only small summaries in `results/`.
- **Git:** commit and push after each finished step. The remote is github.com/KilroyHere/dbkv, through the `github-dbkv` deploy key.
- **Notify Aryan** with `dbkv-notify "<subject>"` (body on stdin), only for a job ending or failing, a gate result, or being blocked on his approval. It mails `ap2568@nersc.gov`; only `nersc.gov` and `lbl.gov` recipients work from Perlmutter.
- **No downloads** (models, datasets, packages) without Aryan's approval.
- **Setup changes** are logged in [docs/PERLMUTTER.md](docs/PERLMUTTER.md), or folded into `setup/perlmutter_setup.sh`.

## Environment

`source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh`: Python 3.11, vLLM, DuckDB in `$SCRATCH/envs/dbkv-env`, `HF_HOME=$SCRATCH/huggingface`. Model: Qwen/Qwen3-8B on 1× A100-SXM4-40GB.

## Where things are

| Path | What |
|---|---|
| `harness/agent/` | The frozen ReAct SQL agent on BIRD (`run_bird.py`, `tools.py`) and its analysis |
| `harness/brief/` | Schema-brief generator (full, compact, lexical, llm, oracle) and D2 analyses |
| `harness/gateway/` | Gateway (admission, priority, routing), open-loop load generator, mock vLLM, summarizer |
| `harness/` | G3 replayer, KV-limit calculator, D5 probe |
| `sim/` | KV simulator (G1, closed) and the open-loop capacity simulator |
| `calib/` | EXPLAIN-vs-runtime calibration (G2, closed direction) |
| `engine/` | Notes on the Continuum fork (cited baseline only) |
| `slurm/` | Job scripts |
| `setup/` | `env.sh`, `perlmutter_setup.sh`, `dbkv-claude`, `dbkv-notify`, `job-nh` |
| `results/` | Small summaries and figures (`figures.py`) |
| `docs/` | OVERVIEW, PLAN (lab notebook), PERLMUTTER (environment log), EXPERT (parked idea), prior-art notes |
