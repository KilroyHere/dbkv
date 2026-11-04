# Perlmutter setup record

How dbkv is set up on Perlmutter, and how to rebuild it. The setup is tracked in three places, all in this repo:

1. **`setup/env.sh`**: the single source of truth for paths, the Python module and the model name. Every job script sources it.
2. **`setup/perlmutter_setup.sh`**: an idempotent script that builds everything from scratch. Re-running it is safe.
3. **`setup/requirements.lock.txt`**: exact package versions, rewritten by the setup script with `pip freeze` and committed after each run.

This file logs the state and any manual steps. If something is changed by hand, write it here, or better, fold it into the script.

## Where things live

| What | Path | Why there |
|---|---|---|
| Repo (git clone of github.com/KilroyHere/dbkv) | `/global/cfs/cdirs/m4999/team19/ap2568/dbkv` | Backed up; teammates can read it through ACLs |
| Python env (CPU tools and stock vLLM) | `$SCRATCH/envs/dbkv-env` | `/global/common/software/m4999` is shared by the whole class and was over quota on 2026-11-04 |
| Data, traces, DuckDB files, run outputs, logs | `$SCRATCH/dbkv/{tpch,bird,traces,runs,logs}` | Fast and large. Purged after 8 weeks without access |
| Model weights | `$SCRATCH/huggingface` (`HF_HOME`) | Shared HF cache from the HWs, which already holds Llama-3.1-8B and CodeLlama-34B |
| Continuum env (vLLM 0.10.2 fork) | Not created yet | Separate env, see `engine/README.md` |

## Day-to-day

```bash
# from the Mac: renew the 24 h cert once a day (only you can, needs your password + OTP)
sshproxy -u ap2568
ssh perlmutter
source /global/cfs/cdirs/m4999/team19/ap2568/dbkv/setup/env.sh
cd $DBKV_REPO && git pull
```

- **Code flow:** edit on the Mac, push to GitHub, then `git pull` on Perlmutter. Pushing from Perlmutter needs GitHub credentials there, which aren't set up.
- **Heavy work goes through Slurm jobs, never the login node.** Each job script sources `setup/env.sh`.
- **tmux sessions are per login node.** The setup session ran on `login14`, while the Claude Code remote session was started on `login33`. Reattach with `ssh -t perlmutter ssh -t <node> tmux attach -t <name>`.

## Budget (from `iris`)

| Allocation | Cap per user | Used | Checked |
|---|---|---|---|
| GPU (m4999_g) | 45 node-hours | 7.7 | 2026-11-03 |
| CPU | 10 node-hours | — | 2026-11-03 |

A 1-GPU `shared` job costs ¼ node-hour per hour and gets 16 cores and 64 GB RAM. Re-check with `iris` before big sweeps.

## Setup log

| Date | Step | Result |
|---|---|---|
| 2026-11-04 | Repo cloned to CFS from GitHub | ok (`cacea18`) |
| 2026-11-04 | `perlmutter_setup.sh --model` on login14 | failed: `/global/common/software/m4999` over quota (shared by the class) |
| 2026-11-04 | Env moved to `$SCRATCH/envs/dbkv-env`; setup re-run in tmux `dbkv-setup` on login33 | running |
