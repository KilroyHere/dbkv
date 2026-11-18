# Phase 2: options A → C → B → E → D on Qwen3-32B (PLAN §2j-A … §2j-D)

**Setup:** Qwen3-32B BF16, TP = 4 on one Perlmutter node (4 × A100-40GB), vLLM 0.33. Agent `agent-32b-v1` on W3 (TPC-H SF10/SF100, TPC-DS SF10). Open-loop Poisson cells: 60 s warm-up, 300 s window, 180 s drain cap. Every comparison is paired inside one job: base and option arms on fresh servers. Predictions were written into PLAN before each step's data.

**Process changes during the phase (all decided by Aryan and recorded in PLAN):**
- A(a) and A(b) had 3 repeats.
- From C on: one paired run, plus a second run (seed 1) when the result was borderline.
- A(c) skipped (no W8A8 checkpoint exists).
- C's second run skipped.
- E's second run timed out; E was stopped there.

**GPU:** 16.1 node-h for Phase 2 (`jobs.tsv`). Project total: 33.2 of 45 (`iris`, Nov 18).

## Final system (tag `system-32b-final`)

**stock vLLM (FCFS) + suffix decoding (A(b)) + EXPLAIN query scheduling (D)**

## Each option, as an added gain on the best system so far

| step | option | plan prediction | measured | verdict | adopted |
|---|---|---|---|---|---|
| A(a) | gateway: whole-task admission K = 135 + task-start priority, vs stock | ≥ 1.5× throughput at overload | 140/min: **1.36×** throughput (1.27 / 1.40 / 1.42); evictions 31–37% → 2–4%. **Correct tasks/min unchanged** (13.5 vs 13.3); window accuracy −2.8 pts. 40 and 60/min: no difference | NOT MET | **no** (accuracy rule) |
| A(b) | suffix decoding, vs stock (re-run on the stock base; confirmatory test on seeds 3–4) | ≥ 1.5× lower p50 at light load | c = 1 p50 **0.59–0.63×**; 40/min p50 −28 to −55%, p95 −27%; 60/min p50 −54 to −57% on 4 of 5 seeds; holds ~53 tasks/min at 140/min where stock collapses to 37–41. Confirmatory accuracy test passed (paired flips 11 vs 18) | **MET** | **yes** |
| A(c) | INT8 W8A8 weights | ≥ 1.3× ceiling | not run: no official W8A8 checkpoint for Qwen3-32B | — | skipped |
| A(d) | FP8 KV cache | ≥ 1.2× ceiling if KV-limited | not runnable: FP8 KV + suffix crashes at start (vLLM 0.33 FlashInfer spec-decode path on A100). KV was not the limit below ~100/min anyway | — | not runnable |
| C | joint speculation + prefill budget (vLLM scheduler plugin) | ≥ 15% throughput at the ceiling vs best static K | vs best static K = 16: **+4.6%** throughput at 60/min; p95 −36% at 40 (one cell); trims drafts in 39% of steps | NOT MET | no (single borderline run; second run skipped) |
| B | goodput gateway (value = P(success) ÷ remaining work; forced final answers under overload) | ≥ 15% more correct tasks/min than the best static turn limit | 140/min: correct/min **16.8** vs turn-limit-8 17.8 vs base **18.8** (2 seeds); finishes 43% more tasks, but the forced finishes are mostly wrong | NOT MET | no |
| E | task-aware eviction (vLLM block-pool plugin) | ≥ 10% fewer prefill tokens at overload | 140/min: prefill per finished task **−7.6%**; live-task evictions 23% → 17%; throughput −1%, accuracy −2.2 pts | NOT MET | no (seed-1 pair timed out) |
| D | EXPLAIN query scheduling in front of DuckDB (short first, caps, 60 s deadline) | ≥ 25% lower p50 with ~32 agents on SF100 | SF100 stream at 40/min, 2 seeds: p50 **216 → 49 s and 85 → 63 s (mean −63%)**; throughput **+33%** (14.2 → 27.0, 24.0 → 23.8); p95 −2%; accuracy +4.6 pts | **MET** | **yes** |

## What we learned

1. **Decode speed is the lever for a dense 32B model.** Suffix decoding roughly halves task time at light and moderate load, and it also avoids the overload collapse.
2. **Admission protects the KV cache but not correctness.**
   - Under overload, stock vLLM ends up favouring short tasks, which are the ones likely to be right.
   - FIFO admission (A(a)) and value-based forcing (B) both spend the GPU on long, mostly failing tasks.
   - As a result, correct answers per minute do not rise.
3. **KV-memory mechanisms (A(d), E) have little to act on.** Below ~100 tasks/min the KV pool is 25–45% used. E's 8% prefill saving does not turn into speed on a compute-bound GPU.
4. **Speculation tuning beyond the default (C) adds little.** Static K = 8/16/24 are within 3% of each other.
5. **The database matters on SF100.**
   - On an all-SF100 load DuckDB is the bottleneck (GPU idle 41%).
   - EXPLAIN-based scheduling (short first, bounded heavy queries, deadline shedding) cuts the median task time by 26–77%.
   - G2 (Nov 4) showed EXPLAIN predicts query time; here it finally has something to act on.
6. **Re-render of the previous reply is 15–29% of uncached prefill.** That is a prompt-side fix none of the options targets.

## Files

- `p2_A.json`: A(a), A(b) on the gateway, A(d) base arm.
- `p2_Ab_stock.json`: the A(b) re-run on stock.
- `p2_C.json`, `p2_B.json`, `p2_E.json`, `p2_D.json`.

Jobs and node-h are in `jobs.tsv` (Aryan's `$SCRATCH/dbkv/logs/`, copy in `dbkv-data/logs/`); Slurm logs of the 32B jobs are in `dbkv-data/logs/`; arm-level tables are in PLAN §2j-A … §2j-D.
