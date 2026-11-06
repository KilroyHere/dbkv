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

## Relation to Team 19's project

The team proposal was a **broker in front of the database** (result caching, query coalescing, speculative execution). We measured the database at only **1–4% of a SQL agent's task time** (3.6% in Test 2; the rest is LLM decoding). So a DB-side broker has little to win, and the work moved to the **serving side**: how the GPU serves many agents. See [docs/OVERVIEW.md §4](docs/OVERVIEW.md#4-ruled-out) for this and the other ruled-out ideas.

## If you're not on Perlmutter

From a GitHub clone (github.com/KilroyHere/dbkv; a normal `git clone` includes the tags `agent-frozen-v1` and `system-frozen-v1`, and in an older clone run `git fetch --tags`) you can:
- **Read every result:** `results/*.md|json|csv|png`, indexed in [results/README.md](results/README.md).
- **Rebuild the 4 figures that need only `results/`:** `fig_g1_gap_vs_ratio`, `fig_g1_policies`, `fig_priority_test`, `fig_phase2_gateway`. Run `python results/figures.py` (needs numpy and matplotlib). It rewrites the figures it can build, writes `fig_g2_explain` with only its right panel, and skips the 7 that need raw run files, with a message. The raw files are on Perlmutter (below); set `DBKV_RAW` to a copy of that `runs/` folder to build all 12.
- **Test the gateway locally against the mock vLLM** (no GPU; `pip install aiohttp numpy`):
  ```bash
  python harness/gateway/mock_vllm.py --port 8100 &                    # fake vLLM: tool calls, then a final SQL
  python harness/gateway/gateway.py --port 9000 --backends http://127.0.0.1:8100 --admission 2 --log /tmp/gw.jsonl &
  mkdir -p /tmp/agent && git show agent-frozen-v1:harness/agent/run_bird.py > /tmp/agent/run_bird.py \
                      && git show agent-frozen-v1:harness/agent/tools.py > /tmp/agent/tools.py
  python harness/gateway/loadgen.py --agent-dir /tmp/agent --url http://127.0.0.1:9000 --gateway \
      --bird <BIRD dev dir> --rate 30 --warmup 5 --measure 20 --drain-cap 20 --out /tmp/lg
  ```
  The load generator runs the real agent's tools on SQLite, so it needs BIRD dev. That's public: download it from bird-bench.github.io, see [docs/REPRODUCE.md](docs/REPRODUCE.md). `--dry-run` prints the arrival schedule without any server.

**To get Perlmutter access:**
1. Request a NERSC account and to be added to project **m4999** (CS 5470), through NERSC Iris; ask the course staff or the project PI.
2. Once you're in, the repo is at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv`, and the raw files the figures need are at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv-data/runs`. Both are readable by the team ACLs (ac3354, sj945, ut25). `results/figures.py` uses the copy automatically, and all 12 figures rebuild from it.
3. Everything else is in Aryan's `$SCRATCH`, which only he can read: BIRD, briefs, other run outputs, the model cache, the envs. Your own `$SCRATCH` and `setup/perlmutter_setup.sh` let you rebuild them ([docs/REPRODUCE.md](docs/REPRODUCE.md)).

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
