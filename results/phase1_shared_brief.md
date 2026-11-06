# Phase 1: a shared whole-DB (compact) brief under load

- **Setup:** compact brief, frozen agent `220001e` (exported), 300 questions (seed 0), prefix caching on. Job 60888614, 0.043 GPU node-h.
- **Comparison:** explore and full come from step 6 (job 60876091): same setup and questions, but a different job and node (no same-job control).

| c | arm | turns | p50 s | p95 s | accuracy | prompt tok/task | KV mean / max | preemptions | prefix hit |
|---|---|---|---|---|---|---|---|---|---|
| 8 | explore | 7.52 | 4.47 | 12.55 | 46.0% | 11,585 | 6% / 19% | 0 | 84.9% |
| 8 | compact | 6.55 | 4.26 | 14.94 | 48.7% | 17,601 | 13% / 27% | 0 | 90.7% |
| 8 | full | 6.32 | 5.51 | 20.37 | 47.3% | 36,106 | 20% / 41% | 0 | 95.5% |
| 32 | explore | 7.63 | 9.18 | 25.36 | 45.7% | 11,761 | 18% / 51% | 0 | 85.3% |
| 32 | compact | 6.42 | 9.17 | 31.99 | 49.7% | 17,127 | 34% / 57% | 0 | 90.9% |
| 32 | full | 6.16 | 13.66 | 47.33 | 47.0% | 35,960 | 47% / 78% | 0 | 95.6% |
| 64 | explore | 7.64 | 16.88 | 45.80 | 46.7% | 11,831 | 27% / 86% | 0 | 85.1% |
| 64 | compact | 6.32 | 16.68 | 47.14 | 49.3% | 16,684 | 48% / 88% | 0 | 90.9% |
| 64 | full | 6.29 | 28.57 | 99.42 | 47.7% | 36,524 | 69% / 100% | 3 | 92.7% |

## Rule P1 (§2f): compact ≥ +5 accuracy points vs explore AND compact p95 ≤ explore p95, at c = 32 and c = 64

- c = 32: Δacc +4.0 (need ≥ +5: no); p95 32.0 vs 25.4 s (no)
- c = 64: Δacc +2.7 (need ≥ +5: no); p95 47.1 vs 45.8 s (no)

**P1: NOT MET** (predicted NOT MET).

## Readings
- **Against the full schema, compact wins clearly under load.** At c = 64: p95 47.1 s vs 99.4 s, p50 16.7 vs 28.6 s, KV mean 48% vs 69%, 0 preemptions vs 3, half the prompt tokens. Accuracy is slightly higher too (49.3% vs 47.7%).
- **Against explore, compact matches p50** (16.7 vs 16.9 s at c = 64; 9.17 vs 9.18 s at c = 32) and gives +2.7 to +4.0 accuracy points. But its tail is worse: p95 +26% at c = 32, +3% at c = 64. It holds ~1.8× explore's KV.
- **Predictions:** accuracy 50.5% predicted vs 49.7%/49.3% observed; p95 27/52 s predicted vs 32.0/47.1 s observed; KV mean 35%/55% predicted vs 34%/48%; prefix hit 90% predicted vs 90.9% (matched).
- *Consistency:* compact at c = 8 here (48.7%, 6.55 turns) vs step-5 compact on all 1,534 questions (50.7%, 6.18 turns): within the n = 300 sampling noise (SE ≈ 2.9 points).
