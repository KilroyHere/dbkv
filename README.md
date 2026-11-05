# dbkv: schema briefs for fast SQL agents

CS 5470 (Aryan Patel). **Current direction (D2):** SQL agents spend about half their turns exploring an unfamiliar database. Can a compact, automatically built schema brief remove those turns, matching an oracle brief's latency and accuracy without the full schema's prompt cost, even under high concurrency?

The earlier direction, D3 (database-informed KV retention while agents wait on SQL), was closed after its gates. Its measurements are kept as the characterization results.

The full plan, current status, go/no-go gates, schedule and budget are in [docs/PLAN.md](docs/PLAN.md). The Perlmutter setup and workflow are in [docs/PERLMUTTER.md](docs/PERLMUTTER.md).

## Layout

| Folder | Contents |
|---|---|
| `docs/` | Plan, prior-art notes, decisions |
| `sim/` | Trace-driven simulator of GPU KV memory and retention policies (gate G1, policy tuning) |
| `calib/` | `EXPLAIN`-vs-runtime calibration on DuckDB: TPC-H and BIRD (gate G2) |
| `harness/` | Session replayer (`replay.py`, gate G3), overhead probe (`d5_probe.py`), KV-limit calculator (`kv_limit.py`) |
| `harness/agent/` | ReAct SQL agent on BIRD (Qwen3-8B via vLLM tool calling, SQLite tools) and its analysis |
| `harness/brief/` | Schema-brief generator built from the database alone (D2) |
| `engine/` | Patches and notes for the Continuum fork of vLLM 0.10.2 |
| `setup/` | `env.sh` (paths), `perlmutter_setup.sh` (rebuild everything), `dbkv-claude` (keep the Claude session alive), the lock file |
| `slurm/` | Perlmutter job scripts (1-GPU `shared` / `shared_interactive`) |
| `results/` | Small summary CSVs, markdown summaries and plots (`figures.py`). Raw traces stay on `$SCRATCH` |

## Where it runs

Everything runs on Perlmutter, driven by an always-on Claude Code session (`setup/dbkv-claude`). The repo lives at `/global/cfs/cdirs/m4999/team19/ap2568/dbkv`, and data and traces go in `$SCRATCH/dbkv/`. Heavy work runs in Slurm jobs, never on login nodes. See [docs/PLAN.md §4a](docs/PLAN.md).

The CPU tools use the `dbkv` environment (`requirements.txt`). The engine work uses a separate `continuum` environment; see `engine/README.md`.
