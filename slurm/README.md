# slurm: Perlmutter job scripts

Every GPU script uses `--constraint=gpu&hbm40g` and sets `--time`. A 1-GPU `shared` job costs ¼ node-h per hour. Log each job in `$SCRATCH/dbkv/logs/jobs.tsv`.

**No GPU jobs run while the project is paused (since Nov 6).** Labels are defined in the [glossary](../docs/OVERVIEW.md#6-glossary); exact submissions are in [docs/REPRODUCE.md](../docs/REPRODUCE.md).

| Script | What it runs | Result | Status |
|---|---|---|---|
| `fullrun.sbatch` | Part C: naive (full schema + stock vLLM) vs ours (compact + gateway "both"), from tag `system-frozen-v1` | PLAN §2g (not run) | **current, waiting for "go"** |
| `gw_multi.sbatch` | Same-job comparisons across vLLM configs (restarts vLLM): stock / both / `--max-num-seqs` caps / direct | `a3_reqcap.md`, `a4_collapse.md` | current |
| `gw_phase2.sbatch` | Gateway on 1 GPU: stock / priority / admission / both × arrival rates; S2 self-check (direct vs gateway) | `phase2_gateway.md` | current |
| `gw_phase3.sbatch` | 2 vLLM replicas behind the gateway: round-robin / least-loaded / affinity routing; S3 self-check | `a2_phase3.md` | closed (routing dropped) |
| `d2_sweep.sbatch` | Brief arms × concurrency 8/32/64, prefix caching on/off, exported frozen agent | `d2_step6.md`, `phase1_shared_brief.md` | current |
| `d2_arms.sbatch` | Brief arms on all 1,534 BIRD dev questions at concurrency 8, exported frozen agent (`DRY_RUN=1` checks without a GPU) | `d2_step5.md` | current |
| `stage_a.sbatch` | Brief-aware prompt check (frozen vs brief-aware, lexical briefs, 150 questions) | `stage_a.md` | closed (failed gate) |
| `agent_bird.sbatch` | ReAct agent on BIRD with HEAD's agent (Tests 2 and 3, agent smoke tests) | `t2_summary.md`, `t3_summary.md` | closed (pre-freeze; runs HEAD, not a tag) |
| `d5_overhead.sbatch` | Test 1: idle probe + loaded points with per-request server timings | `d5_summary.md` | closed (D5 dropped) |
| `g3_sweep.sbatch` | G3 main sweep: replayer × context × sessions, resumable | `g3_summary.md` | closed (G3 done) |
| `g3_smoke.sbatch` | G3 smoke test: vLLM startup, KV pool size, 4 replayer points | PLAN §2 (1a) | closed |
| `g3_priority.sbatch` | Stock vs `--scheduling-policy priority` (task start) on the replayer | `g3_priority_60827432.md` | closed |
| `g1_sim.sbatch` | G1 simulator grid on CPU (pass `--cost-json` / `--pause-file`) | `g1v2_*`, `g1v2b_*` | closed (D3 ruled out) |
| `tpch_gen.sbatch` | TPC-H SF1 + SF10 into DuckDB (CPU) | data for G2 | closed |
| `tpch_sf100.sbatch` | TPC-H SF100 into DuckDB in 10 chunks (CPU) | data for G2 | closed |
| `tpcds_gen.sbatch` | TPC-DS SF1 + SF10 into DuckDB (CPU) | data for G2 | closed |
| `continuum_env.sbatch` | Builds `$SCRATCH/envs/continuum-env` from vllm-continuum (CPU) | env only (cited baseline) | closed |

G2 job scripts live in `calib/` (`g2_sf10.sbatch`, `g2_sf100.sbatch`); they are closed, with results in `g2_sf10_summary.md` and `g2_sf100_summary.md`.
