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

## How work happens: one main Claude, on Perlmutter

```
 You (Claude app: desktop or phone) ──Remote Control──► Claude Code "dbkv-perlmutter"
                                                          in tmux "dbkv" on a login node, cwd = repo
                                                                │ sbatch / squeue
                                                                ▼
                                                    Slurm jobs (CPU / GPU) ──► $SCRATCH/dbkv/runs
 Claude on the Mac (side helper) ──ssh──► check, fix setup        GitHub: KilroyHere/dbkv
```

- **Talk to `dbkv-perlmutter` in the Claude app** for all project work. It keeps running when the laptop is closed.
- **The Mac Claude is a helper only:** Google Docs, the background research report, setup fixes over ssh. Don't have both edit the repo at the same time. If the Mac side changes something, it pushes to GitHub and the Perlmutter side pulls.
- **Long tasks are Slurm jobs,** not processes on the login node. They survive Claude restarts and login-node reboots. Claude watches them with `squeue` and reads outputs from `$SCRATCH/dbkv/runs`.
- **Shared memory between sessions is the repo,** not the chat. Conversation history doesn't move between machines, and the Perlmutter conversation itself can be lost on a restart (see below). Everything that must survive goes in `docs/PLAN.md` (Status section) and this file. `CLAUDE.md` tells every new session to read them first.

## Keeping the session alive: `setup/dbkv-claude`

`~/.local/bin/dbkv-claude` is a symlink to `setup/dbkv-claude`.

| Command | What it does |
|---|---|
| `dbkv-claude start` | Starts tmux session `dbkv` on the current login node, inside the repo, and records the node in `~/.dbkv-claude-node`. Does nothing if it is already alive on its recorded node |
| `dbkv-claude status` | Shows the recorded node, whether it is alive, and the last restart-log lines |
| `dbkv-claude attach` | Opens the tmux session, hopping to the recorded node if needed. From the Mac: `ssh -t perlmutter dbkv-claude attach` |
| `dbkv-claude peek` | One-screen view: last commits, the Status table, Slurm jobs, the job log (`$SCRATCH/dbkv/logs/jobs.tsv`) and the session's last chat messages. The Mac Claude uses this to see what the Perlmutter session is doing |
| `dbkv-claude stop` | Stops the restart loop and the session |

**What survives what:**

| Event | Result |
|---|---|
| Laptop closed, network drops | Nothing changes |
| Claude crashes or exits | The loop restarts it after 30 s with `remote-control --continue`, so the same conversation reattaches if it was active in the last ~4 hours |
| Gap of more than ~4 hours | It starts a fresh conversation in the repo, which reads `CLAUDE.md` and the Status section. The project state carries over; the chat does not |
| Login node rebooted (Perlmutter maintenance) | tmux dies with the node. Run `ssh perlmutter dbkv-claude start` from the Mac. That needs the day's `sshproxy` certificate |
| Slurm jobs during any of the above | Unaffected |

Restarts are logged to `$SCRATCH/dbkv/logs/claude-rc.log`.

## Daily routine

```bash
sshproxy -u ap2568                      # on the Mac, once a day (password + OTP; only you can)
ssh perlmutter dbkv-claude status       # optional health check
```

The Perlmutter session doesn't need the certificate once it is running. You need it only to ssh in from the Mac.

## Email notifications: `setup/dbkv-notify`

`~/.local/bin/dbkv-notify` is a symlink to `setup/dbkv-notify`. Usage: `echo "body" | dbkv-notify "subject"`. It sends `[dbkv] subject` to **`ap2568@nersc.gov`**, which NERSC forwards to Aryan's registered email. Sends are logged in `$SCRATCH/dbkv/logs/notify.log`.

**Only `nersc.gov` and `lbl.gov` recipients work from Perlmutter.** NERSC's mail relay bounces everything else (Gmail included), and `mail` still exits 0, so the log's "ok" means only that the relay took the message. When to send is set out in CLAUDE.md.

## Pushing to GitHub from Perlmutter

A key was generated at `~/.ssh/dbkv_deploy` (public key comment `perlmutter-ap2568-dbkv-deploy`). Until it is added to the repo as a **write** deploy key, the Perlmutter Claude can commit but not push. To add it from the Mac:

```bash
ssh perlmutter cat ~/.ssh/dbkv_deploy.pub > /tmp/dbkv_deploy.pub
gh repo deploy-key add /tmp/dbkv_deploy.pub --repo KilroyHere/dbkv --allow-write --title perlmutter-ap2568
```

On Perlmutter, `~/.ssh/config` has a `Host github-dbkv` entry using that key, and the repo's `origin` is `git@github-dbkv:KilroyHere/dbkv.git`.

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
| 2026-11-04 | Env moved to `$SCRATCH/envs/dbkv-env`; setup re-run on login33 | ok: Python 3.11.7, vLLM 0.33.0, PyTorch 2.14.0+cu130, DuckDB 2.0.0. GPU driver 580.178 (supports CUDA 13) |
| 2026-11-04 | Qwen3-8B download (`--model` step) | ok: 16.4 GB, snapshot `b968826d` |
| 2026-11-04 | Deploy key `~/.ssh/dbkv_deploy` generated; `github-dbkv` ssh alias; origin switched to ssh | key not yet added on GitHub |
| 2026-11-04 | Old setup removed: `team19-rc` launcher, `~/.team19-rc-node`, tmux `claude` (old RC session in the deleted `team19/code`), the failed `/global/common/software/m4999/ap2568` | done |
| 2026-11-04 | `dbkv-claude` installed; session `dbkv` started on login33 | ok: trust prompt answered, Remote Control live as `dbkv-perlmutter` |
| 2026-11-04 | Deploy key added on GitHub | ok: `git ls-remote origin` works over ssh |
| 2026-11-04 | Added `dbkv-claude peek` and the job log `$SCRATCH/dbkv/logs/jobs.tsv` | ok |
| 2026-11-04 | G3 smoke job 60824576 failed at engine start: FlashInfer's JIT lock under `~/.cache` got `flock` errno 524, because `$HOME` doesn't support locking from compute nodes | fixed in `setup/env.sh`: the FlashInfer, vLLM, Triton and Inductor caches now live under `$SCRATCH/cache`. Also measured: A100 `total_memory` = 42,404,806,656 B, and Qwen3-8B weights load as 15.27 GiB |
| 2026-11-04 | `dbkv-notify` added (email). The first 4 mails to Gmail bounced: NERSC's relay only accepts nersc.gov/lbl.gov | `TO` changed to `ap2568@nersc.gov` (forwarded; Aryan tested it). One summary email re-sent |
