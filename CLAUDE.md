# Notes for Claude working in this repo

The project is **dbkv** (direction D3), Aryan Patel's CS 5470 project, done solo. When a SQL agent pauses on a query, the serving engine decides whether to keep, offload or drop that agent's KV cache, using the query optimizer's `EXPLAIN` estimate of how long the query will take.

- **Canonical plan:** [docs/PLAN.md](docs/PLAN.md). Read its **Status** section first. It is the handoff point between sessions, so update it whenever something finishes or a decision changes.
- **Environment record:** [docs/PERLMUTTER.md](docs/PERLMUTTER.md). Log every setup change there, or better, fold it into `setup/perlmutter_setup.sh`.

## Rules

- **Run heavy work in Slurm jobs, never on the login node.** That covers TPC-H generation, query runs, simulator grids and anything on a GPU. Job scripts live in `slurm/` and start with `source setup/env.sh`. Heavy work that doesn't need a GPU goes on **CPU nodes** (`--constraint=cpu`, `shared` QOS), never in a GPU job or on the login node (Aryan, Nov 4).
- **GPU type.** Every GPU job uses `#SBATCH --constraint=gpu&hbm40g`. Plain `gpu` can land on an A100-80GB, which has about 3× the KV pool and invalidates every memory-limit result. That happened to job 60825603 on Nov 4.
- **GPU budget.** About 37 node-hours remain of Aryan's 45 per-user cap (7.7 used as of Nov 3). A 1-GPU `shared` job costs ¼ node-hour per hour. Check `iris` before a sweep, and put each job's estimated node-hours in its commit or log entry.
- **CPU budget.** The cap is 10 node-hours per user. Use small `shared` CPU jobs with 16–32 cores.
- **Never leave GPU jobs running unattended.** Every job gets a `--time` limit. Check `squeue -u $USER` before ending a session.
- **Where things go.** Code goes in this repo (CFS). Data, traces, run outputs and logs go in `$SCRATCH/dbkv`. Only small summaries go in `results/`.
- **Pre-registration.** Before running a gate (G1–G3), write its prediction into PLAN.md. Never edit a prediction after seeing results; add the observed number next to it.
- **Git.** Commit and push after each finished step, so progress is visible on GitHub. The remote is github.com/KilroyHere/dbkv, reached through the `github-dbkv` deploy key.
- **Job log.** When you submit a Slurm job, append one line to `$SCRATCH/dbkv/logs/jobs.tsv`: date, job id, purpose, partition, estimated node-hours. When it ends, fill in that same row's `actual_node_hours` and its end state; don't add a second row. `squeue` drops finished jobs, so a job missing from it is not proof that it finished: check `sacct -j <id>` (or `setup/job-nh <id>...`, which prints state, elapsed and node-hours) for the end state and elapsed time. `dbkv-claude peek` shows this file, and it is how the budget gets tracked.
- **Visibility.** Aryan, and a helper Claude on his Mac, check on you with `dbkv-claude peek`. It shows git, the Status table, Slurm jobs, the job log and your last messages. Keep the Status table current.
- **Email notifications.** Run `dbkv-notify "<subject>"` (in `setup/`, symlinked into `~/.local/bin`), with the body on stdin. It emails Aryan at `ap2568@nersc.gov`, which NERSC forwards to his registered email, with the subject `[dbkv] <subject>`. Only `nersc.gov` and `lbl.gov` recipients work from Perlmutter; the relay bounces anything else, such as Gmail.
  - Send one for exactly these events: a job ending or failing, a gate result (G1–G3), or being blocked on Aryan's approval. These are the same events as push notifications.
  - Put the details in the body: job ID, end state, actual node-hours, and the key number or the question.
  - Send at most one email per event, and none for routine progress.
  - Sends are logged in `$SCRATCH/dbkv/logs/notify.log`.

## Environment

`source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh`. This sets up Python 3.11 with vLLM, DuckDB and the other tools in `$SCRATCH/envs/dbkv-env`, with `HF_HOME=$SCRATCH/huggingface`. The model is Qwen/Qwen3-8B. Continuum (vLLM 0.10.2) gets its own environment later.

This session itself is kept alive by `setup/dbkv-claude`. See PERLMUTTER.md.
