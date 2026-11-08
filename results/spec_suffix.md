# Test S: suffix decoding on the shared workload W (PLAN §2h)

**Pre-registered** Sat Nov 7 2026 16:06 PT (commit 357ff09). Axis B was amended by Aryan before any axis B data (commit 779e714).

**Run** in job **60982784**: 1 A100-40GB, 2 h 08 min, **0.532 node-h** (cap 1.0).
- Agent: the DuckDB port of the frozen agent, tag `agent-duckdb-v1` (1df5a56). BIRD cells use the frozen agent `agent-frozen-v1`.
- Model and server: Qwen3-8B at temperature 0, vLLM 0.33.
- Arms: suffix off vs `--speculative-config '{"method":"suffix"}'` with default settings.
- Each cell gets a fresh server. The arm order alternates by block.
- Smoke cell: job 60982458, 0/20 tasks without SQL, passed.

**Analysis:** `harness/agent_duckdb/analyze_s.py`. Raw numbers are in `results/spec_suffix.json`. Figures are made by `results/fig_spec.py`.

## Verdicts

| Rule | Pre-registered | Prediction | Observed | Verdict |
|---|---|---|---|---|
| **S1h** best case exists | c = 1, 80% repeats: p50(on) ≤ 0.75 × p50(off) | 0.4–0.6× | **0.512×** (4.87 s vs 9.52 s) | **PASS**: kill rule not triggered |
| **S2h** load boundary | smallest c with speedup < 1.05× | between 16 and 64 | speedup 1.96 / 1.67 / 1.47 / 1.73× at c = 1 / 4 / 16 / 64 | **no boundary up to c = 64** (not as predicted) |
| **S3h** repetition dependence | gain(0%) / gain(80%), c = 4, 30 q each | ≈ 0.5 | gain 0.357 vs 0.459, **ratio 0.78** | most of the gain does **not** need template repetition (not as predicted) |
| **S4h** lossless in practice | pooled: accuracy within ±1 point **and** ≥ 95% identical final SQL | met | accuracy on − off **0.0 ± 0.6** points (1,110 pairs); identical SQL **49%** (W 45%, BIRD 77%) | **NOT MET** (accuracy part met, identity part failed) |

## Cell pairs

| stream | N | c | p50 off (s) | p50 on (s) | speedup p50 | speedup p95 | wall off / on (s) | acc off → on | identical SQL | acceptance (on) |
|---|---|---|---|---|---|---|---|---|---|---|
| W r80 | 150 | 1 | 9.52 | 4.87 | **1.96×** | 3.23× | 1861 / 772 | 10.0 → 8.0% | 75/150 | 0.62 |
| W r80 | 150 | 4 | 11.39 | 6.83 | **1.67×** | 2.16× | 534 / 279 | 7.3 → 9.3% | 57/150 | 0.63 |
| W r80 | 300 | 16 | 18.98 | 12.93 | **1.47×** | 1.66× | 500 / 290 | 8.3 → 7.7% | 134/300 | 0.63 |
| W r80 | 300 | 64 | 82.67 | 47.83 | **1.73×** | 2.23× | 555 / 484 | 9.0 → 9.0% | 139/300 | 0.63 |
| W r00 (axis B) | 30 | 4 | 11.76 | 7.56 | **1.55×** | 3.26× | 131 / 68 | 3.3 → 3.3% | 11/30 | 0.58 |
| W r80 (axis B) | 30 | 4 | 10.45 | 5.65 | **1.85×** | 2.05× | 91 / 44 | 6.7 → 6.7% | 13/30 | 0.61 |
| BIRD (frozen agent) | 150 | 1 | 3.11 | 1.60 | **1.94×** | 2.06× | 615 / 288 | 46.7 → 48.0% | 116/150 | 0.60 |

- *Acceptance* is accepted ÷ drafted tokens, from spec-decode counter deltas. Pooled over W on-cells it is 0.627, and about 4 tokens are accepted per draft.
- *Speed per turn type:* with suffix on, decode tokens/s per turn type was roughly 2–3× higher at c = 1–4, for every turn type (explore, execute_sql, final).
- *Wall time at c = 64* is the time until the last task finishes. In the on arm it is stretched by one 258 s straggler. Summed task time per agent is 254 s (on) vs 486 s (off), a ratio of 1.9×, which agrees with the p50 speedup.

## What it means

1. **Suffix decoding works on this agent.** It gives about 2× at low load, and more than 1.4× at every concurrency tested. On BIRD, with the frozen agent and no template repetition, it gives 1.94×. Agent turns emit a lot of text the server has already seen: schema and column names, the agent's own earlier SQL, and tool output echoed back. Suffix drafting turns that into accepted tokens.
2. **The gain does not need repeated templates.** Acceptance with no repeats is 0.58, against 0.61–0.63 with 80% repeats. The 0% cell still gets 1.55×. This is the opposite of the §2h premise, which was that the cross-request tree would carry most of the benefit. Most of it comes from repetition inside each task.
3. **No load boundary up to 64 agents.** The speedup dips at c = 16, then rises at c = 64. At c = 64 the off arm is overloaded (p50 82.7 s, decode about 9 tok/s), and fewer decode steps per task means less queueing. S2h's prediction (boundary between 16 and 64) was wrong. One run per cell, so the dip at 16 may be noise.
4. **Not lossless in practice, though accuracy is unchanged.**
   - Only about half the final SQL strings match between arms. Accuracy is the same within ±0.6 points.
   - The baseline for the identity rate: suffix-off runs reproduce each other exactly. The smoke job and this job's c = 1 off cell agree on **20/20** final SQL.
   - So the arm changes outputs. Verification itself should be exact at temperature 0. But with suffix on, vLLM switches to the V1 model runner, disables async scheduling and caps scheduled tokens at 2048 (PLAN §2h, observed before results). Batch shapes and kernels then differ, near-tie tokens flip, and a long agent trajectory turns that into different SQL.
   - Which of these causes the divergence is **not separated** (see the follow-up below).
   - Divergence is lower on BIRD (77% identical), where trajectories are shorter (7.4 turns vs about 11).

## Caveats

- One run per cell. The S1h margin is wide (0.51 vs 0.75). The c = 16 dip and S3h (30 questions per cell) are coarse.
- The speedup is "the flag as a user gets it". It includes the switch to the V1 runner and the loss of async scheduling, which probably slow the on arm, so the speedup is probably conservative.
- W accuracy is low (3–10%). The agent's prompt still says SQLite, and TPC-DS questions are hard. Accuracy differences are therefore tiny in absolute terms, while the SQL-identity check still covers all 1,110 pairs.

## Decision

- **S1h passed, so the kill rule is not triggered and suffix decoding stays.** It is the first serving-side change in this project with a large, lossless-in-accuracy speedup on the agent workload.
- The plan cache and plan-guided speculation are closed by §2i (Test P2 failed), not by Test S.

**Proposed follow-up, not run (needs Aryan's OK):** one control cell per pair at c = 1 and c = 16, suffix off with `VLLM_USE_V2_MODEL_RUNNER=0` and async scheduling off (about 0.1 node-h). It would split the speedup and the S4h divergence into the suffix part and the runner part. A second run of the c = 16 and c = 64 pairs would show the run-to-run spread.

## Figures

- `fig_spec_speedup_vs_c.png`: p50 speedup vs concurrency (80% repeats).
- `fig_spec_speedup_vs_repeat.png`: p50 speedup at 0% vs 80% repeats (c = 4), with the BIRD reference in the note.
- `fig_plancache_hit_vs_repeat.png`: plan-cache retrieval vs repeat rate (Test P2: top-1 correct, gated recall, false-hint rate).
