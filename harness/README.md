# harness: agent, briefs, gateway, and the G3 / D5 tools

- `replay.py`: G3 synthetic session replayer against a running vLLM server (random-token sessions, sampled SQL pauses, exact prefix extension so prefix caching can hit).
- `kv_limit.py`: predicted KV-memory limit (concurrent resident sessions) for a model on one GPU under vLLM. Pure arithmetic; safe on a login node.
- `g3_summarize.py`: turns a G3 sweep directory into `results/g3_table.csv` and `results/g3_summary.md`.
- `d5_probe.py` / `d5_analyze.py`: Test 1 (D5) idle probe of per-request overhead, and its pre-registered analysis (`results/d5_summary.md`).
- `agent/`: the minimal ReAct SQL agent on BIRD dev. `run_bird.py` (Qwen3-8B via vLLM native tool calling, ≤ 15 turns), `tools.py` (SQLite tools `list_tables`, `describe_table`, `sample_rows`, `execute_sql`), `analyze.py` (Tests 2 and 3). Frozen as tag `agent-frozen-v1`.
- `brief/`: schema briefs built from the database alone. `build.py` (full, compact, lexical, oracle), `llm_select.py` (llm arm), `analyze_d2.py` (step 5), `analyze_sweep.py` (step 6), `stage_metrics.py` (Stage A).
- `gateway/`: `gateway.py` (aiohttp proxy in front of vLLM: admission, task-start priority, routing), `loadgen.py` (open-loop Poisson load running the frozen agent), `mock_vllm.py` (login-node tests), `summarize.py` (per-cell p50/p95, throughput, accuracy), `gw_lib.sh` (shell helpers for `slurm/gw_phase*.sbatch`).
