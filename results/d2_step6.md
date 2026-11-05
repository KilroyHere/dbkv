# D2 step 6: concurrency sweep (300 questions, frozen agent 220001e)

| caching | arm | c | turns | p50 s | p95 s | acc | prompt tok/task | KV mean / p95 / max | preemptions | prefix hit | waiting |
|---|---|---|---|---|---|---|---|---|---|---|---|
| on | explore | 8 | 7.52 | 4.47 | 12.55 | 46.0% | 11585 | 6% / 13% / 19% | 0 | 84.9% | 0.0 |
| on | full | 8 | 6.32 | 5.51 | 20.37 | 47.3% | 36106 | 20% / 34% / 41% | 0 | 95.5% | 0.0 |
| on | lexical | 8 | 5.74 | 4.10 | 12.33 | 49.7% | 10134 | 10% / 17% / 22% | 0 | 80.6% | 0.0 |
| on | oracle | 8 | 5.12 | 3.62 | 11.25 | 55.0% | 8404 | 7% / 14% / 18% | 0 | 78.4% | 0.0 |
| on | explore | 32 | 7.63 | 9.18 | 25.36 | 45.7% | 11761 | 18% / 46% / 51% | 0 | 85.3% | 0.1 |
| on | full | 32 | 6.16 | 13.66 | 47.33 | 47.0% | 35960 | 47% / 74% / 78% | 0 | 95.6% | 0.1 |
| on | lexical | 32 | 5.76 | 9.30 | 28.45 | 48.7% | 10330 | 33% / 52% / 56% | 0 | 80.7% | 0.0 |
| on | oracle | 32 | 5.20 | 7.97 | 25.57 | 54.7% | 8684 | 19% / 47% / 55% | 0 | 79.1% | 0.1 |
| on | explore | 64 | 7.64 | 16.88 | 45.80 | 46.7% | 11831 | 27% / 76% / 86% | 0 | 85.1% | 0.0 |
| on | full | 64 | 6.29 | 28.57 | 99.42 | 47.7% | 36524 | 69% / 98% / 100% | 3 | 92.7% | 2.0 |
| on | lexical | 64 | 5.89 | 17.49 | 55.28 | 50.3% | 10394 | 58% / 98% / 100% | 1 | 79.4% | 0.6 |
| on | oracle | 64 | 5.15 | 14.57 | 40.63 | 54.7% | 8447 | 14% / 83% / 94% | 0 | 78.5% | 0.2 |
| off | explore | 8 | 7.68 | 8.06 | 25.92 | 46.0% | 12128 | 12% / 19% / 27% | 0 | nan% | 0.1 |
| off | full | 8 | 6.20 | 19.89 | 72.48 | 48.0% | 35531 | 33% / 54% / 70% | 0 | nan% | 0.3 |
| off | lexical | 8 | 5.94 | 7.27 | 26.96 | 49.0% | 10860 | 12% / 19% / 28% | 0 | nan% | 0.1 |
| off | oracle | 8 | 5.18 | 6.22 | 21.07 | 56.0% | 8605 | 11% / 16% / 17% | 0 | nan% | 0.0 |
| off | explore | 32 | 7.67 | 26.01 | 77.24 | 46.0% | 12018 | 35% / 53% / 64% | 0 | nan% | 0.9 |
| off | full | 32 | 6.14 | 71.67 | 246.28 | 47.0% | 35348 | 73% / 92% / 98% | 1 | nan% | 12.1 |
| off | lexical | 32 | 5.84 | 21.71 | 75.75 | 49.0% | 9938 | 41% / 52% / 57% | 0 | nan% | 0.8 |
| off | oracle | 32 | 5.20 | 19.27 | 57.84 | 55.0% | 8612 | 38% / 56% / 65% | 0 | nan% | 0.4 |
| off | explore | 64 | 7.63 | 51.13 | 145.31 | 46.0% | 12022 | 57% / 86% / 96% | 0 | nan% | 9.6 |
| off | full | 64 | 6.15 | 142.46 | 441.46 | 47.3% | 35356 | 74% / 94% / 99% | 1 | nan% | 38.2 |
| off | lexical | 64 | 5.85 | 44.76 | 129.47 | 49.3% | 10429 | 67% / 82% / 86% | 0 | nan% | 8.6 |
| off | oracle | 64 | 5.20 | 35.51 | 100.09 | 53.7% | 8661 | 65% / 89% / 97% | 0 | nan% | 5.9 |

## Predictions and rule H (PLAN §2d)

1. Caching on, no preemptions and KV < 90% everywhere: NOT MET (violations: [('full', 64), ('lexical', 64), ('oracle', 64)])
2. Caching off: full over its limit at 32 and 64 (preemptions > 0 and KV ≥ 98%): MET; full p95 at 64 off ≥ 2× on: MET; other arms preempting: none
3. Caching off at c = 8, p50 ratio off/on: explore 1.80, full 3.61, lexical 1.77, oracle 1.72 → NOT MET (full ≥ 1.30, others ≤ 1.15)
4. **Rule H (caching on, c = 32 and 64): DOES NOT HOLD**
   - c = 32: lexical retention 0.77 (≥ 0.60), p95 28.45 vs explore 25.36 (≤) → fails; acc lexical 48.7% vs full 47.0% (reported)
   - c = 64: lexical retention 0.70 (≥ 0.60), p95 55.28 vs explore 45.80 (≤) → fails; acc lexical 50.3% vs full 47.7% (reported)
   - Extra: caching off, c = 64, full p95 / lexical p95 = 3.41 (predicted ≥ 1.5)
