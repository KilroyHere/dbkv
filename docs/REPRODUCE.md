# Reproducing dbkv results

This file explains how every file in [results/](../results/README.md) was made: the environment, the data, the exact Slurm submissions and the analysis step that turns raw output into the summary file. It also lists what a teammate can't read and would need copied.

Job arguments below were taken from the first lines of each job's Slurm log (`$SCRATCH/dbkv/logs/<name>-<job>.out`), from `sacct` (job name, `--time`) and from the job scripts' headers. Dates and node-hours come from `$SCRATCH/dbkv/logs/jobs.tsv`. Labels are defined in the [glossary](OVERVIEW.md#6-glossary).

## Rules before running anything

- **Pre-register first.** Before running a gate, test or §2j step, write its prediction (and any pass/fail rule) into [PLAN.md](PLAN.md) and commit it. Never edit a prediction after seeing data; add the observed number next to it. Since Nov 15 the current plan is PLAN §2j (Part C, §2g, is superseded and will not be run).
- **Heavy work goes in Slurm jobs, never on a login node.** Every script in `slurm/` starts with `source setup/env.sh`.
- **GPU jobs:** always use `--constraint=gpu&hbm40g` and an explicit `--time`. Plain `gpu` can land on an A100-80GB, and that happened to jobs 60825603 and 60825810, whose data is invalid. All `slurm/*.sbatch` GPU scripts already set the constraint. A 1-GPU `shared` job costs ¼ node-hour per hour; a full node (regular QOS, §2j) costs 1 node-hour per hour. Check `iris` before each GPU phase and `squeue -u $USER` before leaving.
- **Log every job.** Append one line to `$SCRATCH/dbkv/logs/jobs.tsv` when you submit (date, job id, purpose, partition, estimated node-hours). Fill in the actual node-hours when it ends; `setup/job-nh JOBID` computes them from `sacct`.
- **Frozen code.** Runs after Nov 5 use exported copies of tagged files, not HEAD (see [Git tags](#git-tags)).

## Environment

| What | Where / how |
|---|---|
| Paths, module, caches | `source setup/env.sh` from your clone. It sets `DBKV_REPO` (the clone `env.sh` lives in; Aryan's clone on CFS is the fallback), `DBKV_DATA=$SCRATCH/dbkv`, `DBKV_ENV=$SCRATCH/envs/dbkv-env` (venv, activated if present), `HF_HOME=$SCRATCH/huggingface`, `DBKV_MODEL=Qwen/Qwen3-8B`, and loads module `python/3.11-24.1.0`. It also puts the FlashInfer, vLLM, Triton, Inductor, uv and pip caches under `$SCRATCH/cache`, because `$HOME` doesn't support `flock` from compute nodes (jobs 60824576 and 60825842 failed on that). |
| Rebuild the env | `bash setup/perlmutter_setup.sh` on a login node. It is idempotent and creates `$DBKV_DATA/{tpch,bird,traces,runs,logs}`, makes the venv, installs `requirements.txt` + `setup/requirements-gpu.txt`, and rewrites `setup/requirements.lock.txt` with `pip freeze`. `requirements-gpu.txt` doesn't pin vLLM. To get the exact stack, install from `setup/requirements.lock.txt` instead: vLLM 0.33.0, PyTorch 2.14.0, DuckDB 2.0.0, sqlglot 30.29.0, Python 3.11.7. |
| Model (§2j, since Nov 15) | `DBKV_MODEL=Qwen/Qwen3-32B`. `bash setup/perlmutter_setup.sh --model` runs `hf download Qwen/Qwen3-32B --exclude "*.pth"` into `$HF_HOME` (~65 GB, BF16; run it in tmux; needs Aryan's approval). Served as BF16, non-thinking, temperature 0. Snapshot hash recorded in [PERLMUTTER.md](PERLMUTTER.md) once downloaded. |
| vLLM server flags (§2j, full node) | Base, to be confirmed by the Phase 0 smoke test: `vllm serve Qwen/Qwen3-32B --tensor-parallel-size 4 --gpu-memory-utilization 0.9 --max-model-len 32768 --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 --enable-auto-tool-choice --tool-call-parser hermes`. Option switches add `--scheduling-policy priority` (A(a), with the gateway), `--speculative-config '{"method": "suffix"}'` (A(b)), a W8A8 checkpoint (A(c)) and `--kv-cache-dtype fp8` (A(d)). The exact flags of each job are in its Slurm log. |
| Model (8B record) | `bash setup/perlmutter_setup.sh --model` with `DBKV_MODEL=Qwen/Qwen3-8B` ran `hf download Qwen/Qwen3-8B --exclude "*.pth"` into `$HF_HOME`. It took 16.4 GB (snapshot `b968826d`). Served as bf16, non-thinking, temperature 0. |
| vLLM server flags (8B agent jobs) | `vllm serve Qwen/Qwen3-8B --gpu-memory-utilization 0.9 --max-model-len 32768 --enable-prefix-caching --enable-prompt-tokens-details --enable-per-request-metrics --seed 0 --enable-auto-tool-choice --tool-call-parser hermes`, plus `--scheduling-policy priority` for the priority/both configs. KV pool: 139,232 tokens (134,448 in one early start). |
| Continuum (cited only, never run in experiments) | `sbatch slurm/continuum_env.sbatch` builds `$SCRATCH/envs/continuum-env` from `$SCRATCH/src/vllm-continuum` (github.com/Hanchenli/vllm-continuum @ `316a587`, vLLM 0.10.2). Job 60826039. |

Setup history and fixes are in [PERLMUTTER.md](PERLMUTTER.md).

## Data

Everything is under `$DBKV_DATA` = `/pscratch/sd/a/ap2568/dbkv` for Aryan.

| Dataset | Path | How it was made |
|---|---|---|
| BIRD dev (1,534 questions, 11 SQLite DBs) | `bird/dev_20240627/` (1.8 G), `bird/dev.zip` (331 M) | Official download: `https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip`, linked from bird-bench.github.io. The server reports the same byte size, 346,207,293, as our copy. Downloaded Nov 4 evening on a login node with `cd $DBKV_DATA/bird && curl -sL --retry 4 -C - -o dev.zip https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip && unzip -q dev.zip && cd dev_20240627 && unzip -q dev_databases.zip` (not scripted in the repo). |
| TPC-H SF1, SF10 (DuckDB) | `tpch/tpch_sf{1,10}.duckdb` | `sbatch slurm/tpch_gen.sbatch`, job 60823995 (Nov 4, 21 s) |
| TPC-H SF100 | `tpch/tpch_sf100.duckdb` (`tpch/` is 30 G in total) | `sbatch slurm/tpch_sf100.sbatch`, job 60824952 (Nov 4, 19:45) |
| TPC-DS SF1, SF10 | `tpcds/tpcds_sf{1,10}.duckdb` (3.2 G) | `sbatch slurm/tpcds_gen.sbatch`, job 60824954 (Nov 4) |
| Schema briefs | `briefs/briefs_{full,compact,lexical,oracle}.jsonl` (`briefs/` is 25 M) | `python harness/brief/build.py --bird $DBKV_DATA/bird/dev_20240627 --variant <v> --out $DBKV_DATA/briefs/briefs_<v>.jsonl [--eval]` (Nov 5 12:38–12:43). These are CPU-only and light. |
| `lexical_desc` brief (Stage A only) | `briefs/briefs_lexical_desc.jsonl` | `python harness/brief/build.py --bird $DBKV_DATA/bird/dev_20240627 --variant lexical_desc --reuse $DBKV_DATA/briefs/briefs_lexical.jsonl --out $DBKV_DATA/briefs/briefs_lexical_desc.jsonl --eval` (run in `srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:10:00`; default `--desc-chars 80`). It reuses the step-5 lexical selection, so only the descriptions differ. |
| `llm` brief | `briefs/briefs_llm.jsonl` (copy of `runs/d2/60873675/briefs_llm.jsonl`) | Built inside job 60873675 by `python harness/brief/llm_select.py --url $URL --bird $BIRD --out $OUT/briefs_llm.jsonl --concurrency 8 --eval` (it needs the running vLLM server) |
| **W3 analytics workload (§2j)** | `$DBKV_DATA/w3/`: `bank/{bank,attempts}.jsonl` (validated gold instances of the 121 W2 templates on `tpch/tpch_sf{10,100}.duckdb` and `tpcds/tpcds_sf10.duckdb`), `streams/w3_{mix,h100}_s{0..4}.jsonl` (3000 tasks each since Nov 15 srun 61371151; the first 1000 are byte-identical to the original n = 1000 build; gold rows inline), `brief_{tpch,tpcds}_compact.txt`. Made by `srun -A m4999 -C cpu -q shared_interactive -c 32 --mem=80G -t 01:30:00 bash slurm/w3_build.sbatch` (job 61362847, Nov 15, 4.4 min; `python harness/w3/build_w3.py bank --draws 6 --workers 4 --threads 8` then `streams --n 1000 --seeds 0 1 2 3 4`) and the briefs by `python harness/plancache/brief.py <tenant>.duckdb <out>` on `tpch_sf10` / `tpcds_sf10` (srun 61362635). Checksums: `results/w3_SHA256SUMS`; summaries `results/w3_bank_summary.json`, `results/w3_streams_summary.json`. Tag `workload-w3-v1`. |
| Frozen briefs (final system) | `frozen/system-v1/briefs_{compact,full}.jsonl` + `SHA256SUMS` (17 M) | Byte-identical copies of `briefs/briefs_{compact,full}.jsonl`. Their sha256 sums are in the `system-frozen-v1` tag message, and `slurm/fullrun.sbatch` checks them before running. |

## Git tags

- **§2j tags (planned, Nov 15):** `agent-32b-v1` (the DuckDB agent ported to Qwen3-32B and W3, set after the Phase 0 smoke test), `workload-w3-v1` (W3 templates, gold SQL and stream generator), `system-32b-<step>` (best system after each Phase 2 step). `agent-duckdb-v1` (Nov 7) is the W port for 8B.

- **`agent-frozen-v1`** = `220001e`: the frozen ReAct agent (`harness/agent/run_bird.py`, `tools.py`). Qwen3-8B non-thinking, temperature 0, max_tokens 1024, ≤15 turns, final-turn answer. Check: 150 tasks, 0% no-SQL, 46.0% accuracy (job 60872839).
- **`system-frozen-v1`** = `0002aae`: the final system. Gateway files `harness/gateway/{gateway,loadgen,summarize}.py` and `gw_lib.sh` at this commit, plus the agent above and the frozen briefs.
- **Full-run jobs export tagged files, never HEAD:**
  - `d2_sweep.sbatch`, `gw_phase2/3.sbatch`, `gw_multi.sbatch` and `stage_a.sbatch` export the agent from `agent-frozen-v1` (`git show agent-frozen-v1:harness/agent/...`) into `$DBKV_DATA/tmp/frozen_agent.XXXX`.
  - `fullrun.sbatch` also exports the gateway from `system-frozen-v1` (override with `SYSTEM_TAG`).
- **Fixed Nov 6 (was a gotcha):** HEAD's `run_bird.py` differs from `agent-frozen-v1`, because commit `a812dca` added `--prompt brief_aware` (off by default). `slurm/d2_arms.sbatch` used to refuse to run when they differed. Since `02d29a6` it exports the tagged agent like `d2_sweep.sbatch` does, and `DRY_RUN=1 bash slurm/d2_arms.sbatch <arms>` checks the export and the brief files without a GPU. `slurm/agent_bird.sbatch` (Tests 2–3, pre-freeze) still runs HEAD's agent.

## Commands per result

Shorthand used below: `D=$DBKV_DATA` (`/pscratch/sd/a/ap2568/dbkv`). Run analysis commands from the repo root with `setup/env.sh` sourced. They are light enough for a small `shared` CPU job or `srun` interactive.

### Gates (Nov 4)

**G3 KV limit:** `g3_summary.md`, `g3_table.csv`, `fig_g3_limit.png`
```bash
sbatch slurm/g3_smoke.sbatch                                                          # 60824741 (smoke, --time 0:30)
sbatch --time=04:30:00 --job-name=g3_sweep_4k8k slurm/g3_sweep.sbatch 4096,8192        # 60825601, 0.83 node-h
sbatch --time=02:20:00 --job-name=g3_sweep_20k  slurm/g3_sweep.sbatch 20480            # 60827431, 0.43 node-h (redo on 40GB)
# both write $D/runs/g3/main (RUN_NAME=main); the sweep script runs the summarizer at the end:
python harness/g3_summarize.py $D/runs/g3/main      # -> $D/runs/g3/main/g3_{summary.md,table.csv}; copied to results/
python harness/kv_limit.py --ctx 4096 8192 20480    # the prediction (login-node safe)
```

**Priority test:** `g3_priority_60827432.md`, `fig_priority_test.png`
```bash
sbatch slurm/g3_priority.sbatch                     # 60827432, --time 1:30, 0.22 node-h; -> $D/runs/g3_priority/60827432/{priority,fcfs}
```
The Markdown table was written by an inline analysis step in the working session (not a repo script) from the replayer's `summary.json` files. No script in the repo produces it. The figure's numbers are hard-coded in `results/figures.py:priority_test()`.

**G3 costs refit and sim fidelity:** `g3_costs.json`, `g3_costs_meta.json`, `g1_fidelity.csv`
```bash
python sim/refit_costs.py $D/runs/g3/main --out results/g3_costs.json          # also writes g3_costs_meta.json
python sim/fidelity.py $D/runs/g3/main --costs results/g3_costs.json --out results/g1_fidelity.csv   # srun 60832770
```

**G2 `EXPLAIN` calibration:** `g2_sf10_summary.*`, `g2_sf100_summary.*`, `g2_sf100_pauses.txt`, `fig_g2_explain.png`
```bash
sbatch calib/g2_sf10.sbatch     # 60825416, TPC-H SF10 + TPC-DS SF10, 0.024 CPU node-h
sbatch calib/g2_sf100.sbatch    # 60826277, TPC-H SF100, 0.136 CPU node-h
# each job ends with: python calib/g2_analyze.py $D/runs/g2/<job>   -> summary.{md,json}, copied to results/g2_<sf>_summary.*
```
`results/g2_sf100_pauses.txt` is a copy of `$D/runs/g2/60826277/pauses_sf100.txt`, written by an inline step (not a repo script): the `median_s` column of `$D/runs/g2/60826277/results.csv` for every query with a median (707 values), one per line (`numpy.savetxt(..., fmt='%.6f')`).

**G1 oracle simulation:** `g1_gap.csv`, `g1v2_*`, `g1v2b_*`, `fig_g1_*.png`
```bash
sbatch slurm/g1_sim.sbatch                                     # v1: 60824732 (sim at commit 3ec5a1b) -> results/g1_gap.csv
sbatch slurm/g1_sim.sbatch                                     # v2a: 60825742, guessed costs
sbatch slurm/g1_sim.sbatch --cost-json $DBKV_REPO/results/g3_costs.json \
                           --pause-file $DBKV_REPO/results/g2_sf100_pauses.txt   # v2b: 60832776, 0.086 CPU node-h
```
The files in `results/` are the **re-aggregated** outputs, made with the throughput-validity rule added in `79b6154`:
- `g1v2_*` = `$D/runs/g1/60825742/agg/`
- `g1v2b_*` = `$D/runs/g1/60832776/agg/`

Commands used (login node; light):
```bash
python sim/g1_grid.py --from-results $D/runs/g1/60825742/results.csv --out $D/runs/g1/60825742/agg
python sim/g1_grid.py --from-results $D/runs/g1/60832776/results.csv --out $D/runs/g1/60832776/agg \
    --pause-file results/g2_sf100_pauses.txt --cost-json results/g3_costs.json
# then: cp agg/{gap,breaker}.csv and agg/gap_vs_ratio.png to results/g1v2_* (60825742) and results/g1v2b_* (60832776)
``` **Careful:** `g1_grid.py` (without `--quick`) copies its output to `results/g1v2_*`, overwriting the v2a files. After a v2b run, rename the outputs to `g1v2b_*` and restore `g1v2_*` from git.

### Overnight decision tests (Nov 4)

These ran the agent at commit `ea04dd4`, before the freeze. `agent_bird.sbatch` uses HEAD's agent, so check out `ea04dd4` first to reproduce them exactly.
```bash
sbatch slurm/d5_overhead.sbatch                                                       # Test 1: 60839032
python harness/d5_analyze.py $D/runs/d5/60839032 --out results/d5_summary.md          # also d5_summary.json

sbatch --time=01:00:00 --job-name=t2_agent slurm/agent_bird.sbatch 1:none 8:none      # Test 2: 60839247
python harness/agent/analyze.py t2 --c1 $D/runs/agent/60839247/c1_none --c8 $D/runs/agent/60839247/c8_none \
    --out results/t2_summary.md

sbatch --time=01:00:00 --job-name=t3_brief slurm/agent_bird.sbatch 8:full 8:oracle   # Test 3: 60839248
python harness/agent/analyze.py t3 --a $D/runs/agent/60839247/c8_none --b $D/runs/agent/60839248/c8_full \
    --c $D/runs/agent/60839248/c8_oracle --out results/t3_summary.md
```

### D2 schema briefs (Nov 5)

**Agent freeze check:** `AGENT_N` defaults to 150.
```bash
sbatch --time=00:30:00 --job-name=agent_fix2 slurm/agent_bird.sbatch 8:none          # 60872839 (agent @ 220001e)
```

**Step 5, brief arms:** `d2_step5.{md,json}`, `fig_d2_arms.png`, `fig_d2_acc_vs_tokens.png`, `fig_d2_time_breakdown.png`
```bash
sbatch --job-name=d2_A slurm/d2_arms.sbatch explore full       # 60873599, 0.17 node-h
sbatch --job-name=d2_B slurm/d2_arms.sbatch compact lexical    # 60873600, 0.15 node-h
sbatch --job-name=d2_C slurm/d2_arms.sbatch llm oracle         # 60873675, 0.19 node-h (builds briefs_llm first)
python harness/brief/analyze_d2.py \
    --arm explore=$D/runs/d2/60873599/explore --arm full=$D/runs/d2/60873599/full \
    --arm compact=$D/runs/d2/60873600/compact --arm lexical=$D/runs/d2/60873600/lexical \
    --arm llm=$D/runs/d2/60873675/llm --arm oracle=$D/runs/d2/60873675/oracle --out results/d2_step5.md
```
This is the exact `--arm` list that was run (confirmed by Aryan's session).

**Step 6, concurrency sweep:** `d2_step6.{md,json}`, `fig_d2_sweep.png`, `d2_kv_accounting.md`
```bash
CELLS="explore:8 full:8 lexical:8 oracle:8 explore:32 full:32 lexical:32 oracle:32 explore:64 full:64 lexical:64 oracle:64"
sbatch --job-name=d2_sw_on  slurm/d2_sweep.sbatch on  $CELLS    # 60876091, 0.21 node-h
sbatch --job-name=d2_sw_off slurm/d2_sweep.sbatch off $CELLS    # 60876092, 0.42 node-h
python harness/brief/analyze_sweep.py --on $D/runs/d2sweep/60876091 --off $D/runs/d2sweep/60876092 --out results/d2_step6.md
```
`d2_kv_accounting.md` was a one-off analysis of 60876091's `metrics.jsonl`, `turns.jsonl` and `server.log`. Its script isn't in the repo.

**Phase 1, shared compact brief:** `phase1_shared_brief.md`
```bash
sbatch --time=01:00:00 --job-name=p1_compact slurm/d2_sweep.sbatch on compact:8 compact:32 compact:64   # 60888614, 0.043 node-h
```
The Markdown was assembled by an inline analysis step in the working session (not a repo script) from this job and 60876091 (same columns as `analyze_sweep.py`, whose `ARMS` list doesn't include compact).

**Stage A:** `stage_a.{md,json}`
```bash
sbatch slurm/stage_a.sbatch     # 60879976 (repo a812dca); ends with harness/brief/stage_metrics.py ... --gate --out $OUT/stage_a.md
```

**Expert adapter:** `expert_*`. It was run from branch `expert` with `harness/expert/expert.sbatch` (job 60873555). Only the docs and results were merged, not `harness/expert/`, so it can't be rerun from `main`. See [EXPERT.md](EXPERT.md).

### Serving: gateway, routing (Nov 5–6)

**Open-loop simulator:** `openloop_sim_summary.{md,json}`
```bash
srun -q shared_interactive -A m4999 -C cpu -c 32 -t 0:20:00 python sim/openloop_rates.py --out $D/runs/openloop --procs 32   # 60888767
cp $D/runs/openloop/summary.md results/openloop_sim_summary.md; cp $D/runs/openloop/summary.json results/openloop_sim_summary.json
```
The exact `srun` flags aren't recorded (sacct shows 32 CPUs, 0:20 limit). The output files match `results/` byte for byte.

**Self-check S2, then Phase 2:** `phase2_gateway.{md,json}`, `fig_phase2_gateway.png`. Defaults from `gw_lib.sh`: W=120, M=480, drain=600, seed 0.
```bash
sbatch --job-name=gw_s2b --time=01:00:00 slurm/gw_phase2.sbatch stock:110 direct:110             # S2 pass: 60890137 (fail: 60889433)
GW_K=77 sbatch --job-name=gw_p2_fcfs slurm/gw_phase2.sbatch stock:110 admission:110 stock:190 admission:190 stock:250 admission:250  # 60891199
GW_K=77 sbatch --job-name=gw_p2_prio slurm/gw_phase2.sbatch priority:110 both:110 priority:190 both:190 priority:250 both:250     # 60891201
python harness/gateway/summarize.py $D/runs/gw_phase2/60891199 $D/runs/gw_phase2/60891201 --out <prefix>
```
`summarize.py` returns a list of cells. `results/phase2_gateway.json` holds the same cells re-keyed as `"<policy>|<rate>"`; every p95 and throughput value was checked and matches. The re-keying step and the Markdown's "sim" column (from `openloop_sim_summary.md`) were done by hand.

**Self-check S3 and A2 routing:** `a2_phase3.md`
```bash
GW_BRIEFS=none sbatch --job-name=gw_s3  --gpus=1 --cpus-per-task=32 --time=01:00:00 slurm/gw_phase3.sbatch 1 affinity:110 direct:110   # 60891207 (explore agent)
GW_BRIEFS=none sbatch --job-name=gw_s3b --gpus=1 --cpus-per-task=32 --time=01:00:00 slurm/gw_phase3.sbatch 1 affinity:110 direct:110   # 60892403
GW_WARMUP=60 GW_DRAIN=180 GW_MEASURE=480 sbatch --job-name=a2_p3_compact --time=02:00:00 slurm/gw_phase3.sbatch 2 \
    round_robin:380 least_loaded:380 affinity:380 affinity:500 least_loaded:500 round_robin:500                          # 60912394, 0.68 node-h
GW_WARMUP=60 GW_DRAIN=180 GW_MEASURE=480 GW_BRIEFS=$D/briefs/briefs_full.jsonl sbatch --job-name=a2_p3_full --time=01:30:00 \
    slurm/gw_phase3.sbatch 2 round_robin:380 affinity:380 affinity:500 round_robin:500                                    # 60912395, 0.48 node-h
```
Each job writes `$D/runs/gw_phase3/<job>/summary.md` through `summarize.py`, and `a2_phase3.md` was assembled by an inline analysis step in the working session (not a repo script) from those. The env vars come from the logged values (W=60, M=480, drain=180, cap=1.25); how they were passed is inferred.

**A3 request cap and A4 collapse:** `a3_reqcap.md`, `a4_collapse.md`, `fig_a3_reqcap.png`, `fig_load_curve.png`. `gw_multi` defaults: K=77, W=60, M=300, drain=180.
```bash
sbatch --job-name=a3_reqcap   --time=01:00:00 slurm/gw_multi.sbatch reqcap64:250 both:250 reqcap32:250             # 60912396, 0.13 node-h
sbatch --job-name=a4_collapse --time=01:15:00 slurm/gw_multi.sbatch stock:210 both:210 both:230 stock:230           # 60912397, 0.15 node-h
```
Each job ends with `summarize.py`, which writes `$D/runs/gw_multi/<job>/summary.md` plus a `summary.json` per cell. The `results/` Markdown was assembled by an inline analysis step in the working session (not a repo script) from those.

**Part C (not run).** It is pre-registered in PLAN §2g:
```bash
GW_K=72 sbatch --job-name=c_rep1 slurm/fullrun.sbatch naive:100 naive:170 naive:230 naive:300 ours:100 ours:170 ours:230 ours:300
```

### Figures
```bash
python results/figures.py      # raw data from $DBKV_RAW, else the CFS copy dbkv-data/runs, else $SCRATCH; overwrites all results/fig_*.png
```
[results/README.md](../results/README.md#figures-what-figurespy-needs) says which figures can be rebuilt from `results/` alone.

## Qwen3-32B experiments (PLAN §2j)

Everything from Nov 15 on: Phases 0–2 (`results/p1_baseline.md`, `results/p2_summary.md`). One script runs every GPU cell, `slurm/node_p1.sbatch`.

### 1. One-time setup (your own account)

```bash
git clone git@github.com:KilroyHere/dbkv.git && cd dbkv          # or work in a clone on CFS
source setup/env.sh                                              # DBKV_REPO = this clone, DBKV_DATA = $SCRATCH/dbkv
bash setup/perlmutter_setup.sh --model                           # venv + vLLM 0.33 + arctic-inference + our 3 plugins + Qwen3-32B (~65 GB; run in tmux)
```

- The setup script installs `arctic-inference==0.1.1` (needed for suffix decoding; built with GCC 13, see PERLMUTTER.md Nov 7) and our plugins `harness/vllm_{steplog,jointspec,taskevict}` (editable, inert unless switched on).
- Check: `python -c "from importlib.metadata import entry_points as e; print(e(group='vllm.general_plugins'))"` lists `dbkv_jointspec` and `dbkv_taskevict`.

### 2. Data

- **DuckDB files:** `setup/dbkv-sbatch slurm/tpch_gen.sbatch` (TPC-H SF1/SF10), `setup/dbkv-sbatch slurm/tpch_sf100.sbatch` (SF100, ~20 min, 27 GiB), `setup/dbkv-sbatch slurm/tpcds_gen.sbatch` (TPC-DS SF1/SF10). These are CPU jobs that write to `$DBKV_DATA/{tpch,tpcds}/`.
- **W3 workload**, either:
  - **rebuild it** (5 min CPU, identical streams for the same seeds, but gold rows are computed on *your* files):
    ```bash
    srun -A m4999 -C cpu -q shared_interactive -c 32 --mem=80G -t 01:00:00 bash slurm/w3_build.sbatch
    python harness/plancache/brief.py $DBKV_DATA/tpch/tpch_sf10.duckdb $DBKV_DATA/w3/brief_tpch_compact.txt   # in an srun
    python harness/plancache/brief.py $DBKV_DATA/tpcds/tpcds_sf10.duckdb $DBKV_DATA/w3/brief_tpcds_compact.txt
    ```
  - **or copy Aryan's** from the team folder and rewrite the DuckDB paths inside the streams:
    ```bash
    rsync -a /global/cfs/cdirs/m4999/team19/ap2568/dbkv-data/w3/ $DBKV_DATA/w3/
    sed -i "s#/pscratch/sd/a/ap2568/dbkv#$DBKV_DATA#g" $DBKV_DATA/w3/streams/*.jsonl $DBKV_DATA/w3/bank/*.jsonl
    ```
    (`results/w3_SHA256SUMS` matches the files before this path rewrite; check it before running `sed` if you need to.)
- **Option B's table:** `dbkv-data/goodput/b_train_s12.json` → `$DBKV_DATA/goodput/`. It is rebuilt by `harness/gateway/fit_goodput.py` (PLAN §2j-B lists the training jobs and seeds).

### 3. Submitting

```bash
cd <repo root>
setup/dbkv-sbatch [-q debug] --time=HH:MM:SS --job-name=NAME slurm/node_p1.sbatch CELL ...
```

- `setup/dbkv-sbatch` = sbatch from the repo root, with the log in `$DBKV_DATA/logs/NAME-JOBID.out`.
- Outputs go to `$DBKV_DATA/runs/p1/JOBID/`:
  - one directory per cell, with `tasks.jsonl`, `turns.jsonl`, `metrics_0.jsonl`, `summary.json`, and `gateway.jsonl` if any;
  - `server_K.log` and `server_K_steps.jsonl` per vLLM start;
  - `cells.tsv` and `servers.tsv`.
- Knobs (env):
  - `P1_SEED` (stream and load seed, default 0);
  - `P1_STREAM` (default `w3_mix_s$P1_SEED`; option D uses `w3_h100_s*`);
  - `P1_WARMUP` / `P1_MEASURE` / `P1_DRAIN` (60 / 300 / 180 s);
  - `AGENT_TAG` (`agent-32b-v1`);
  - `TASK_KV` (2,260 → K = pool / TASK_KV);
  - `GP_TABLE`, `JS_BUDGET`, `JS_THETA`, `JS_MIN`, `TE_MODE`, `TE_PORT`.
- `DRY_RUN=1 bash slurm/node_p1.sbatch CELL ...` on a login node checks the plan and stops at the GPU check.
- **Cost:** a full node is 1 node-h per hour. `debug` QOS (≤ 30 min) usually starts within minutes; `regular` full-node jobs waited 30 min to 3 h in Nov 2026. Log every job in `$DBKV_DATA/logs/jobs.tsv` (AGENTS.md rules).

**Cells** (run in order on one server; the prefix cache is reset between cells):
- `server:CFG`: restart vLLM with `+`-joined switches:
  - `fcfs` (stock), `prio` (`--scheduling-policy priority`);
  - `suffix` (suffix decoding, K = 24) or `suffixN` (static K = N);
  - `js` (option C), `te` (option E), `fp8`, `w8a8`.
- `closed:C:N`: N tasks, C concurrent agents (light load).
- `open:RATE`: open-loop Poisson load, tasks/min.
- `gw:RATE:K|auto`: through the gateway with admission K and priority (option A(a)).
- `gwx:RATE:SET`: gateway flag sets:
  - `tl8`: static turn limit 8;
  - `gp`: option B;
  - `gpp`: B without forcing;
  - `pt`: pass-through;
  - `te`: pass-through + option E tags.
- `openx:RATE:SET`: load-generator sets: `dbdef` (DuckDB default), `dbx` (option D), `dbobs` (D's classifier in observe mode).
- `burst`, `restart:on|off`: synthetic burst and instrumentation on/off.

**The exact runs behind each result** (seeds 0 / 1 / 2 as `P1_SEED`; arm order alternated by seed):

| result | cells |
|---|---|
| Phase 1 sweep | `burst open:60 open:100` · `open:140 open:180` · `open:40 restart:off burst restart:on burst` · `open:20 open:30` (4 debug jobs) |
| Phase 1 repeats | `closed:1:30 closed:4:60 open:40 open:60` |
| A(a) | `server:fcfs open:40 open:60 open:140` + `server:prio gw:40:auto gw:60:auto gw:140:auto` |
| A(b) (stock base) | `server:fcfs closed:1:30 open:40 open:60` + `server:fcfs+suffix closed:1:30 open:40 open:60` |
| C | `server:fcfs+suffix open:60 open:40` + `server:fcfs+suffix16 …` + `server:fcfs+suffix8 …` + `server:fcfs+suffix+js …` |
| B | `server:fcfs+suffix open:40 open:140` + `server:fcfs+suffix gwx:40:tl8 gwx:140:tl8` + `server:prio+suffix gwx:40:gp gwx:140:gp` |
| E | `server:fcfs+suffix gwx:140:pt` + `server:fcfs+suffix+te gwx:140:te` (debug) |
| D | `P1_STREAM=$DBKV_DATA/w3/streams/w3_h100_sN.jsonl`: `server:fcfs+suffix openx:40:dbdef` + `server:fcfs+suffix openx:40:dbx` (debug or regular 0:45) |

Job ids, seeds and dates are in PLAN §2j-P1 … §2j-D and in `results/README.md`.

### 4. Analysis

```bash
python harness/w3/analyze_p1.py $DBKV_DATA/runs/p1/<job> [<job> ...] --out results/<name>.json
```

- Per cell it reports p50/p95, throughput, accuracy, the LLM / DB / DB-queue time split, prefix-cache miss causes and step-log stats.
- `servers.tsv` maps each cell to its server config.
- Correct tasks/min (B), prefill per finished task (E) and paired per-task accuracy flips (A(b)) are short scripts over `tasks.jsonl` / `turns.jsonl`; their definitions are written into PLAN §2j-B / E / A.
- Figure: `python results/fig_p1.py`.

### 5. Adding a new option

1. Make it a switch that is **off by default**:
   - a server switch: an env var or flag set in `cfg_flags()` of `slurm/node_p1.sbatch`;
   - a gateway flag set: a new case under `gwx`;
   - a load-generator flag set: a new case under `openx`.
2. Test it without a GPU: `harness/gateway/mock_vllm.py` stands in for vLLM; vLLM plugins can be unit-tested on a CPU node (see `harness/vllm_jointspec/tests`).
3. **Pre-register** the arms, cells and prediction in PLAN before the first job, then run **one paired job**: base arm and option arm, **each on a fresh server**.
4. Analyse with `analyze_p1.py`; record the verdict and the adoption decision in PLAN.

### 6. Gotchas we hit

- **The suffix-decoding tree persists between cells on one server** (`reset_prefix_cache` does not clear it). Later cells get faster, so give every arm its own `server:` restart and keep cell order the same across arms. This biased B's turn-limit arm in job 61476626.
- **FP8 KV + suffix decoding crashes at start** on A100 with vLLM 0.33 (FlashInfer spec-decode path).
- **`step_ms` in the step log is launch time** under async scheduling, not GPU time. Use token counts and vLLM's throughput log.
- **Accuracy under load flips both ways** with any change to batching (nondeterministic numerics). Judge accuracy with paired per-task flips over several hundred tasks, not one window's percentage.
- **A few load-independent long tasks** (SQL timeouts on SF100, 15-turn runaway generation) dominate p95 and can be unfinished at any rate. Below capacity, compare medians and paired counts.
- **The debug QOS limit is 30 min:** a two-arm 140/min job barely fits (E seed 1 timed out).

## What a teammate can and cannot read

- **Can read:** this repo on CFS (through ACLs) and on GitHub. That covers all of `results/`, the code, the job scripts and the docs.
- **Cannot read:** anything in Aryan's `$SCRATCH` (`/pscratch/sd/a/ap2568/...`). Perlmutter scratch is per-user. That includes raw runs, BIRD, TPC-H/DS, briefs, frozen briefs, logs, the model cache and the envs. A teammate's own `$SCRATCH` is a different directory, so `figures.py`'s `$SCRATCH/dbkv/runs/...` paths would resolve to their own (empty) scratch. To reuse copied files without editing code, put them at the same relative paths under the teammate's `$SCRATCH/dbkv/runs/`.

**Raw files needed for the figures that can't be built from `results/` alone.** Sizes are from `du`, measured Nov 6.

| Figure | Files under `/pscratch/sd/a/ap2568/dbkv/runs/` | Size |
|---|---|---|
| `fig_g2_explain.png` (left panel) | `g2/60825416/results.csv`, `g2/60826277/results.csv` | 444 K + 184 K = 628 K |
| `fig_g3_limit.png` | `g3/main/rep*/c*_n*_r0/summary.json` and `turns.csv` (96 files, 48 runs) | 1.9 M (whole `g3/main` is 8.6 M) |
| `fig_d2_time_breakdown.png`, `fig_d2_arms.png`, `fig_d2_acc_vs_tokens.png` | `tasks.jsonl` + `turns.jsonl` in `d2/60873599/{explore,full}`, `d2/60873600/{compact,lexical}`, `d2/60873675/{llm,oracle}` | 5.3 + 4.5 + 4.5 + 4.4 + 4.4 + 4.0 = 27 M |
| `fig_d2_sweep.png` | `d2sweep/60876091/*_c*/tasks.jsonl`, `d2sweep/60876092/*_c*/tasks.jsonl`, `d2sweep/60888614/compact_c*/tasks.jsonl` | 2.5 M + 2.5 M + 628 K ≈ 5.6 M |
| `fig_load_curve.png` | `gw_multi/60912397/{stock,both}_r{210,230}/summary.json` (+ `results/phase2_gateway.json`) | 28 K together with the A3 files below |
| `fig_a3_reqcap.png` | `gw_multi/60912396/{reqcap64,reqcap32,both}_r250/summary.json` | (included above) |
| **Total for all figures** | | **≈ 35 M** |

To rerun experiments rather than redraw figures, a teammate would also need:
- BIRD dev (1.8 G, or re-download the official zip, which is public)
- `briefs/` (25 M, rebuildable with `build.py`)
- `frozen/system-v1/` (17 M)
- for G2: `tpch/` (30 G) and `tpcds/` (3.2 G), both regenerable with the gen scripts
- their own env and model download

**Copied Nov 6 (Aryan's decision):** exactly these files, 144 of them, 35 MB, keeping the `runs/` layout, are at **`/global/cfs/cdirs/m4999/team19/ap2568/dbkv-data/runs/`**. That directory is readable by group m4999 and by the team ACLs (ac3354, sj945, ut25). `results/figures.py` reads raw data from `$DBKV_RAW` if set, else this CFS copy, else `$SCRATCH/dbkv/runs`. **All 12 figures rebuild from the CFS copy alone** (checked in srun job 60921122 with `SCRATCH` unset: every PNG byte-identical to the committed one). Nothing else was copied then.

**Copied Nov 18 (Qwen3-32B work, Aryan's decision), to the same team folder:**
- `dbkv-data/runs-32b/`: every Phase 0–2 GPU job directory, `<job>/<cell>/...` (610 MB). Rebuilds every `results/p1_*` / `p2_*` JSON with `harness/w3/analyze_p1.py`.
- `dbkv-data/w3/`: W3 bank, streams and briefs (129 MB). The streams hold Aryan's DuckDB paths; see "Qwen3-32B experiments → Data" for the one-line path rewrite.
- `dbkv-data/goodput/`: option B's tables.
- Not copied: the model (download it), the env (rebuild it) and the DuckDB files (regenerate them).
