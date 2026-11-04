# dbkv: database-informed KV retention for SQL agents

CS 5470 Team 19, direction D3. When a SQL agent pauses for a query, the serving engine decides whether to keep, offload or drop that agent's KV cache, using the query optimizer's `EXPLAIN` estimate of how long the query will take.

The full plan, current status, go/no-go gates, schedule and budget are in [docs/PLAN.md](docs/PLAN.md). The Perlmutter setup and workflow are in [docs/PERLMUTTER.md](docs/PERLMUTTER.md).

## Layout

| Folder | Contents |
|---|---|
| `docs/` | Plan, prior-art notes, decisions |
| `sim/` | Trace-driven simulator of GPU KV memory and retention policies (gate G1, policy tuning) |
| `calib/` | `EXPLAIN`-vs-runtime calibration on DuckDB: TPC-H and BIRD (gate G2) |
| `harness/` | ReAct agent for recording traces, the proxy that attaches query-class hints, and the session replayer (gate G3, main runs) |
| `engine/` | Patches and notes for the Continuum fork of vLLM 0.10.2 |
| `setup/` | `env.sh` (paths), `perlmutter_setup.sh` (rebuild everything), `dbkv-claude` (keep the Claude session alive), the lock file |
| `slurm/` | Perlmutter job scripts (1-GPU `shared` / `shared_interactive`) |
| `results/` | Small summary CSVs and plots only. Raw traces stay on `$SCRATCH` |

## Where it runs

Everything runs on Perlmutter, driven by an always-on Claude Code session (`setup/dbkv-claude`). The repo lives at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv`, and data and traces go in `$SCRATCH/dbkv/`. Heavy work runs in Slurm jobs, never on login nodes. See [docs/PLAN.md §4a](docs/PLAN.md).

The CPU tools use the `dbkv` environment (`requirements.txt`). The engine work uses a separate `continuum` environment; see `engine/README.md`.
