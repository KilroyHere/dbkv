# Notes for Claude working in this repo

**Read [AGENTS.md](AGENTS.md) first.** It has the reading order, the current state and all the rules. This file holds only the Claude-specific bits.

- **The Perlmutter session** is kept alive by `setup/dbkv-claude`: tmux session `dbkv`, Remote Control name `dbkv-perlmutter`. Use `dbkv-claude peek` (git, Status, Slurm jobs, job log, last messages), `dbkv-claude status` or `dbkv-claude attach`. See [docs/PERLMUTTER.md](docs/PERLMUTTER.md).
- **The Mac Claude is a read-only helper.** It checks on this session with `ssh perlmutter dbkv-claude peek` and doesn't edit the repo at the same time.
- **The main session is the only writer of `docs/PLAN.md`.** Keep its Status table current, since `peek` shows it.
- **History:** an expert session ran in the worktree `dbkv-expert` on branch `expert` until Nov 5. It is stopped and the idea is parked (see [docs/EXPERT.md](docs/EXPERT.md)).

## Environment

`source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh`. This sets up Python 3.11 with vLLM, DuckDB and the other tools in `$SCRATCH/envs/dbkv-env`, with `HF_HOME=$SCRATCH/huggingface`. The model is Qwen/Qwen3-8B. Continuum (vLLM 0.10.2) is in `$SCRATCH/envs/continuum-env`.
