# results/: index

This folder holds small summaries (Markdown, JSON, CSV) and the figures. Raw runs, traces and logs live in Aryan's `$SCRATCH` (`/pscratch/sd/a/ap2568/dbkv`), which teammates can't read. [docs/REPRODUCE.md](../docs/REPRODUCE.md) explains how each file was made and which raw files would have to be copied over.

Labels (G1–G3, Test 1–3, D2–D5, Phase 1–3, P1–P3, A1–A4, arms, policies, K) are defined in the glossary, [docs/OVERVIEW.md §6](../docs/OVERVIEW.md#6-glossary). The short version:
- **G1/G2/G3** are the go/no-go gates: oracle simulation, `EXPLAIN` calibration and the KV memory limit.
- **Test 1–3** were the Nov 4 overnight decision tests.
- **D2 step 5/6** are the schema-brief comparison (all 1,534 questions) and the concurrency sweep.
- **Phase 1/2/3** were the Nov 5–6 serving tests: shared brief, gateway on 1 GPU, routing on 2 GPUs. **P1/P2/P3** are their pass/fail rules.
- **A2–A4** are the Nov 6 Part A runs: routing, request-cap baseline and collapse point.
- **Arms:** explore (no brief), full, compact, lexical, llm, oracle.
- **Policies:** stock, priority, admission, both, reqcap32/64.

Setup for every GPU number: Qwen/Qwen3-8B (bf16, non-thinking, temperature 0) on one NVIDIA A100-SXM4-40GB (NERSC Perlmutter), vLLM 0.33.0, KV pool 139,232 tokens. Benchmark: BIRD dev, 1,534 questions over 11 SQLite databases.

## Findings

| # | Claim (key number) | Result file(s) | Figure | Job ids | Date |
|---|---|---|---|---|---|
| 1 | **Time anatomy.** Decode is 78–90% of a real agent's task time (explore arm 89%). The DB is 3.6% (Test 2), rising to ~15% when briefs cause runaway SQL. Explore spends 53.5% of its turns exploring the schema. | `t2_summary.md`, `t2_summary.json`, `d2_step5.md` | `fig_d2_time_breakdown.png` | Test 2 60839247; step 5 60873599 / 60873600 / 60873675 | Nov 4–5 |
| 2 | **KV memory limit (G3).** `harness/kv_limit.py` predicted 32 / 16 / 6.5 concurrent sessions at 4k / 8k / 20k context. The measured cliff is right there: full-hit fraction ~0.9 at the predicted N, 0.10–0.34 one step above. | `g3_summary.md`, `g3_table.csv` | `fig_g3_limit.png` | smoke 60824741; sweep 60825601 + 60827431 | Nov 4 |
| 3 | **Priority test.** Program-level (task-start) priority on real vLLM cut p95 by 3–23% above the limit. | `g3_priority_60827432.md` | `fig_priority_test.png` | 60827432 | Nov 4 |
| 4 | **D2 step 5, brief arms** (all 1,534 questions, concurrency 8). Accuracy: explore 43.5%, full 50.4% (34k prompt tokens/task), compact 50.7% (15k), lexical 49.3% (10k), llm 49.0% (8.6k), oracle 58.3% (8.5k). | `d2_step5.md`, `d2_step5.json` | `fig_d2_arms.png`, `fig_d2_acc_vs_tokens.png` | 60873599 / 60873600 / 60873675 (agent freeze check 60872839) | Nov 5 |
| 5 | **Step 6 sweep** (300 questions, c = 8/32/64, prefix caching on/off). The full schema's p95 doubles at 64 agents (99 s vs explore's 46 s). Turning prefix caching off doubles every median. | `d2_step6.md`, `d2_step6.json` | `fig_d2_sweep.png` | 60876091 (on) / 60876092 (off) | Nov 5 |
| 6 | **Phase 1, shared brief.** Compact matches explore's p50 but has a worse tail (P1 not met). It halves full's p95 at c = 64. | `phase1_shared_brief.md` | `fig_d2_sweep.png` (compact line) | 60888614 | Nov 5 |
| 7 | **KV accounting.** Full's extra KV comes from more requests in flight plus per-DB briefs held once. Per-agent tokens are about the same as explore's, and prefix duplication is negligible. | `d2_kv_accounting.md` | none | analysis of 60876091 | Nov 5 |
| 8 | **Phase 2, gateway** (explore agent, Poisson arrivals). At 250 tasks/min, "both" has p95 144 s vs stock's ≥786 s (−82%) and throughput 199 vs 105/min (1.9×). Admission alone gives −74%, priority alone −45%. Overhead is <0.3 ms/req and GPU idle is 0%. Self-check S2 passed on retry. | `phase2_gateway.md`, `phase2_gateway.json` | `fig_phase2_gateway.png` | 60891199 / 60891201 (S2: 60889433 fail, 60890137 pass) | Nov 5–6 |
| 9 | **A3, request cap** (250/min, one job, K = 77). Both: p95 101 s vs 306 s for `--max-num-seqs 64` (−67%), throughput 197 vs 130 (151%). Why: a request cap limits running *requests*, so tasks still interleave between turns and lose their cached prefixes (prefix hit 65% vs 86%); task admission queues whole tasks at the gateway instead (see [OVERVIEW §3.4](../docs/OVERVIEW.md#34-the-gateway)). | `a3_reqcap.md` | `fig_a3_reqcap.png` | 60912396 | Nov 6 |
| 10 | **A4, collapse point and load curve.** Stock throughput falls below arrivals between 190 and 210/min (~200/min). The gateway plateaus at ~190–200/min. | `a4_collapse.md` | `fig_load_curve.png` | 60912397 (+ Phase 2 60891199 / 60891201) | Nov 6 |
| 11 | **Open-loop simulator predictions.** `sim/openloop.py` predicted a capacity of ~190/min and a >80% p95 cut, before any Phase 2 run. | `openloop_sim_summary.md`, `openloop_sim_summary.json` | none | 60888767 (CPU, srun) | Nov 5 |
| 12 | **A2 routing (negative).** DB-affinity + load cap vs round-robin on 2 replicas: compact −3% p95 at 500/min (+29% worse at 380), full −1%. P3 not met, so routing was dropped. Self-check S3 passed only under amendment A1. | `a2_phase3.md` | none | 60912394 (compact) / 60912395 (full); S3 60891207 / 60892403 | Nov 5–6 |
| 13 | **Sim fidelity.** The G1 simulator vs real vLLM at G3's cells is within ±14% above the KV limit and underestimates resume latency below it. | `g1_fidelity.csv` | none | 60832770 (CPU, srun) | Nov 4 |
| 14 | **G3 costs refit.** The simulator's per-iteration cost parameters were fitted to G3 measurements (decode fit R² 0.945, KV pool 139,232). G1 v2b, fidelity and the open-loop simulator all use them. | `g3_costs.json`, `g3_costs_meta.json` | none | fit to 60825601 + 60827431 | Nov 4 |

**Final system** (tag `system-frozen-v1` = `0002aae`): compact whole-DB brief + gateway "both" (admission K = 72 + task-start priority) on 1 GPU, no routing. Part C (naive vs ours, docs/PLAN.md §2g) is pre-registered but **not run**, so no file here.

## Ruled out

| Direction / test | Claim (key number) | Result file(s) | Figure | Job ids | Date |
|---|---|---|---|---|---|
| **G1 v1 / v2 (D3 mechanism:** `EXPLAIN`-informed KV keep/offload/drop) | Knowing each SQL call's duration buys ≤6% p95 at realistic pause lengths, with no crossover up to 30× pauses. Released Continuum is 11–46% worse than always-keep + program FCFS at realistic pauses (cited only). | v1: `g1_gap.csv`. v2a (guessed costs): `g1v2_gap.csv`, `g1v2_breaker.csv`, `g1v2_gap_vs_ratio.png`. **v2b (G3 costs + SF100 pauses, the one cited):** `g1v2b_gap.csv`, `g1v2b_breaker.csv`, `g1v2b_gap_vs_ratio.png` | `fig_g1_gap_vs_ratio.png`, `fig_g1_policies.png` | v1 60824732; v2a 60825742; v2b 60832776 (all CPU) | Nov 4 |
| **G2 `EXPLAIN` calibration** (works, but nothing to act on) | `EXPLAIN` does predict SQL time: on SF100, unseen-template ρ 0.83 and 3-class accuracy 68.6% vs 43.4% for per-template history. SF10 was ambiguous because 93.5% of its queries are short. | `g2_sf100_summary.md`, `g2_sf100_summary.json`, `g2_sf10_summary.md`, `g2_sf10_summary.json`, `g2_sf100_pauses.txt` (SF100 query times, reused as G1 v2b's pause mix) | `fig_g2_explain.png` | SF10 60825416; SF100 60826277 (CPU) | Nov 4 |
| **Test 1 (D5, stateful sessions)** | Per-request overhead outside prefill is 1.9% of p95 turn latency, so D5 was dropped. | `d5_summary.md`, `d5_summary.json` | none | 60839032 | Nov 4 |
| **Test 2 (broker / DB result caching, and D4)** | The DB is 3.6% of task time. Repeated SQL is 0.7% of DB time within a task and 5.2% across tasks, so the broker was dropped. D4 rule: 87% of slow tasks are wrong ("pursue"), but D4 was never pursued. | `t2_summary.md`, `t2_summary.json` | none | 60839247 | Nov 4 |
| **Test 3 (D2 pilot)** | Schema-brief pilot: turns −51.5%, so D2 was pursued by rule. It led to step 5 rather than being a result on its own. | `t3_summary.md`, `t3_summary.json` | none | 60839248 | Nov 4 |
| **Stage A, brief-aware prompt** | `describe_table` calls on brief tables fell from 2.17 to 0.64/task, but the gate needed ≤0.3. Nudged prose turns rose from 0.69 to 2.52. Failed, so Stage B was not run. | `stage_a.md`, `stage_a.json` | none | 60879976 | Nov 5 |
| **Expert adapter** (a BIRD LoRA writes the SQL; [docs/EXPERT.md](../docs/EXPERT.md)) | Accuracy +2.0 ± 2.6 pts, but 3.3× more invented names and p50 +87%. Parked as a negative result. | `expert_stage1.md`, `expert_stage1.json`, `expert_stage0.md`, `expert_stage0.json`, `expert_contam.md` (SFT split vs BIRD dev: 0 overlap) | none | Stage 1.3 60873555 (branch `expert`; Stage 0 reuses Test 2/3 traces) | Nov 5 |

## Other / supporting files

- `figures.py`: the script that draws every `fig_*.png` (see below).
- `README.md`: this file.

Every file in `results/` is listed in one of the tables above or here.

## Figures: what `figures.py` needs

`python results/figures.py` rebuilds **all** figures in one go and overwrites the committed PNGs. Raw run files are read from `$DBKV_RAW` if set, else from the **team-readable CFS copy `/global/cfs/cdirs/m4999/team19/ap2568/dbkv-data/runs/`** (35 MB, copied Nov 6), else `$SCRATCH/dbkv/runs`. The table below names each figure's raw files relative to that runs/ root (written as Aryan's `/pscratch/...` path).

| Figure | Function | Built from `results/` alone? | What it reads |
|---|---|---|---|
| `fig_g1_gap_vs_ratio.png` | `g1()` | **Yes** | `results/g1v2b_gap.csv` (the `--g1` default) |
| `fig_g1_policies.png` | `g1()` | **Yes** | `results/g1v2b_gap.csv` |
| `fig_priority_test.png` | `priority_test()` | **Yes** | Nothing: the 4 p95 pairs are hard-coded from `g3_priority_60827432.md` |
| `fig_phase2_gateway.png` | `phase2()` | **Yes** | `results/phase2_gateway.json` |
| `fig_g2_explain.png` | `g2()` | **Partly.** The right panel (accuracy) comes from `results/g2_sf10_summary.json` and `results/g2_sf100_summary.json`. The left scatter needs raw data and is silently left empty without it | `/pscratch/sd/a/ap2568/dbkv/runs/g2/60825416/results.csv`, `/pscratch/sd/a/ap2568/dbkv/runs/g2/60826277/results.csv` |
| `fig_g3_limit.png` | `g3()` | No (prints "no G3 data yet") | `/pscratch/sd/a/ap2568/dbkv/runs/g3/main/rep*/c*_n*_r0/summary.json` and `turns.csv` in the same dirs |
| `fig_d2_time_breakdown.png` | `d2_breakdown()` | No | `/pscratch/sd/a/ap2568/dbkv/runs/d2/60873599/{explore,full}/`, `.../60873600/lexical/`, `.../60873675/oracle/`, each `tasks.jsonl` + `turns.jsonl` |
| `fig_d2_arms.png` | `d2_arms()` | No | `/pscratch/sd/a/ap2568/dbkv/runs/d2/60873599/{explore,full}/`, `.../60873600/{compact,lexical}/`, `.../60873675/{llm,oracle}/`, each `tasks.jsonl` + `turns.jsonl` |
| `fig_d2_acc_vs_tokens.png` | `d2_acc_vs_tokens()` | No | Same six arm dirs as `fig_d2_arms.png` |
| `fig_d2_sweep.png` | `d2_sweep()` | No | `/pscratch/sd/a/ap2568/dbkv/runs/d2sweep/60876091/<arm>_c{8,32,64}/tasks.jsonl` (caching on), `.../60876092/<arm>_c{8,32,64}/tasks.jsonl` (off), `.../60888614/compact_c{8,32,64}/tasks.jsonl` (Phase 1 compact) |
| `fig_load_curve.png` | `part_a()` | No. The 110/190/250 points come from `results/phase2_gateway.json`, but the 210/230 points need raw data | `/pscratch/sd/a/ap2568/dbkv/runs/gw_multi/60912397/{stock,both}_r{210,230}/summary.json` |
| `fig_a3_reqcap.png` | `part_a()` | No | `/pscratch/sd/a/ap2568/dbkv/runs/gw_multi/60912396/{reqcap64,reqcap32,both}_r250/summary.json` |

The two non-`fig_` plots, `g1v2_gap_vs_ratio.png` and `g1v2b_gap_vs_ratio.png`, are not drawn by `figures.py`. They come from `plot()` in `sim/g1_grid.py`, written when the grid ran. You can redraw them from the matching `results/g1v2*_gap.csv` by calling `sim.g1_grid.plot(rows, path)`; the script has no command-line option for this.

**Summary:** 4 figures rebuild from `results/` alone (G1 ×2, priority test, Phase 2). `fig_g2_explain.png` rebuilds only partly. 7 need raw run files. **On Perlmutter (project m4999), all 12 rebuild from the CFS copy `dbkv-data/runs/`** (verified Nov 6, byte-identical). From a GitHub clone without that copy, only the first 4 work.
