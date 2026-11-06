# Open-loop simulator: capacity and Phase 2 predictions (sim/openloop.py)

Workload: tasks resampled from the explore arm, all 1,534 BIRD dev questions (job 60873599), token counts + tool times only. Engine: kvsim iteration model, pool 139,232 tokens, budget 2048, max 256 seqs, shared 464-token system prompt resident once. Models: **g3** = g3_costs.json; **cal** = c_dec, c_att x 2.0 (fit to step-6 closed-loop cells).

## Closed-loop fidelity (sim vs step 6 explore, caching on; p50/p95 s)

| N | real | g3 sim | cal sim | g3 thr/min | cal thr/min |
|---|---|---|---|---|---|
| 8 | 4.47 / 12.55 | 4.08 / 11.88 | 4.48 / 13.06 | 94 | 86 |
| 16 | - | 5.31 / 15.41 | 6.05 / 17.66 | 144 | 127 |
| 32 | 9.18 / 25.36 | 7.77 / 22.51 | 9.31 / 26.89 | 197 | 165 |
| 48 | - | 10.20 / 29.70 | 12.63 / 36.74 | 225 | 182 |
| 64 | 16.88 / 45.80 | 12.65 / 36.51 | 15.83 / 46.18 | 242 | 193 |
| 80 | - | 15.12 / 43.67 | 19.07 / 55.27 | 253 | 200 |
| 96 | - | 18.12 / 52.89 | 22.83 / 66.56 | 252 | 199 |
| 112 | - | 25.41 / 75.68 | 30.77 / 89.72 | 207 | 172 |
| 128 | - | 36.29 / 104.12 | 41.13 / 117.28 | 166 | 147 |
| 160 | - | 57.05 / 155.85 | 64.11 / 175.37 | 133 | 118 |

## K

- g3: time-averaged context per active task = 1802 tokens (incl. 464 shared) -> K = floor(139232 / 1802) = **77**; context -25% -> K = 103, +25% -> K = 61. Grid also runs K x 0.75 and K x 1.25.
- cal: time-averaged context per active task = 1810 tokens (incl. 464 shared) -> K = floor(139232 / 1810) = **76**; context -25% -> K = 102, +25% -> K = 61. Grid also runs K x 0.75 and K x 1.25.

## Stock capacity sweep (30-min window, 3 seeds)

**g3**: last stable 220/min, first saturated 240/min, capacity ~230/min, max throughput 222/min. Rates: {'below': 140, 'at': 230, 'above': 300}

| lambda | completed/arrived | thr/min | p50 | p95 | active growth | preempt |
|---|---|---|---|---|---|---|
| 60 | 0.999 | 60 | 3.9 | 10.9 | 2 | 0 |
| 80 | 1.000 | 80 | 4.2 | 11.9 | 1 | 0 |
| 100 | 1.001 | 100 | 4.5 | 13.1 | -1 | 0 |
| 120 | 1.000 | 121 | 5.0 | 14.5 | -1 | 0 |
| 140 | 0.998 | 141 | 5.7 | 16.3 | 8 | 0 |
| 160 | 1.000 | 161 | 6.4 | 18.4 | -1 | 0 |
| 180 | 1.000 | 182 | 7.4 | 21.6 | -1 | 0 |
| 200 | 1.003 | 202 | 8.9 | 26.0 | -20 | 0 |
| 220 | 1.003 | 222 | 11.0 | 32.3 | -21 | 2 |
| 240 | 0.481 | 116 | 636.2 | 1457.3 | 3757 | 74 |
| 260 | 0.344 | 90 | 976.5 | 1769.4 | 5135 | 49 |
| 280 | 0.290 | 82 | 1071.9 | 1883.1 | 6001 | 42 |
| 300 | 0.268 | 81 | 1114.1 | 1933.4 | 6625 | 38 |
| 320 | 0.250 | 80 | 1151.3 | 1969.1 | 7246 | 20 |
| 340 | 0.234 | 80 | 1184.0 | 1993.7 | 7859 | 19 |
| 360 | 0.219 | 80 | 1208.8 | 2016.6 | 8496 | 16 |
| 380 | 0.208 | 79 | 1232.2 | 2035.7 | 9097 | 13 |
| 400 | 0.196 | 79 | 1253.6 | 2055.9 | 9715 | 12 |
| 420 | 0.186 | 79 | 1273.7 | 2072.8 | 10337 | 12 |

**cal**: last stable 180/min, first saturated 200/min, capacity ~190/min, max throughput 182/min. Rates: {'below': 110, 'at': 190, 'above': 250}

| lambda | completed/arrived | thr/min | p50 | p95 | active growth | preempt |
|---|---|---|---|---|---|---|
| 60 | 0.999 | 60 | 4.2 | 12.2 | 3 | 0 |
| 80 | 0.999 | 80 | 4.8 | 13.7 | 2 | 0 |
| 100 | 1.001 | 100 | 5.4 | 15.7 | -2 | 0 |
| 120 | 1.001 | 121 | 6.4 | 18.7 | -4 | 0 |
| 140 | 1.000 | 141 | 7.9 | 23.1 | 1 | 0 |
| 160 | 1.002 | 161 | 10.1 | 29.6 | -8 | 0 |
| 180 | 1.000 | 182 | 13.9 | 41.6 | 2 | 68 |
| 200 | 0.429 | 86 | 817.7 | 1587.6 | 3451 | 78 |
| 220 | 0.338 | 75 | 986.1 | 1799.1 | 4389 | 57 |
| 240 | 0.301 | 73 | 1054.2 | 1871.8 | 5064 | 46 |
| 260 | 0.275 | 72 | 1108.0 | 1929.5 | 5677 | 29 |
| 280 | 0.254 | 72 | 1147.2 | 1968.3 | 6312 | 18 |
| 300 | 0.235 | 71 | 1183.1 | 1999.7 | 6920 | 13 |
| 320 | 0.220 | 71 | 1209.2 | 2025.0 | 7535 | 14 |
| 340 | 0.206 | 71 | 1236.3 | 2047.0 | 8142 | 9 |
| 360 | 0.194 | 70 | 1259.1 | 2063.1 | 8776 | 12 |
| 380 | 0.183 | 70 | 1279.5 | 2078.2 | 9383 | 6 |
| 400 | 0.173 | 70 | 1296.1 | 2094.2 | 10001 | 4 |
| 420 | 0.164 | 69 | 1313.0 | 2105.3 | 10620 | 3 |

## Policies, 8-min window (mean ± sd over 5 seeds)

| model | rate | lambda | policy | K | p50 s | p95 s | thr/min | preempt | queue wait mean s | idle | unfinished |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cal | below | 110 | admission | 57 | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | admission | 76 | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | admission | 95 | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | both | 57 | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | both | 76 | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | both | 95 | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | priority | - | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | stock | - | 5.9 ± 0.3 | 17.2 ± 1.2 | 111 ± 2 | 0 | 0.0 | 0.000 | 0 |
| cal | at | 190 | admission | 57 | 27.4 ± 7.5 | 54.8 ± 8.8 | 186 ± 2 | 0 | 11.4 | 0.000 | 0 |
| cal | at | 190 | admission | 76 | 19.7 ± 3.2 | 51.1 ± 6.0 | 190 ± 3 | 0 | 2.4 | 0.000 | 0 |
| cal | at | 190 | admission | 95 | 18.7 ± 3.1 | 52.6 ± 8.1 | 191 ± 4 | 15 | 0.8 | 0.000 | 0 |
| cal | at | 190 | both | 57 | 27.4 ± 7.5 | 54.8 ± 8.8 | 186 ± 2 | 0 | 11.4 | 0.000 | 0 |
| cal | at | 190 | both | 76 | 19.6 ± 3.2 | 51.1 ± 6.0 | 190 ± 3 | 0 | 2.4 | 0.000 | 0 |
| cal | at | 190 | both | 95 | 18.5 ± 2.8 | 51.9 ± 7.2 | 191 ± 4 | 18 | 0.7 | 0.000 | 0 |
| cal | at | 190 | priority | - | 21.5 ± 6.1 | 90.9 ± 57.1 | 181 ± 12 | 235 | 0.1 | 0.000 | 0 |
| cal | at | 190 | stock | - | 23.4 ± 7.9 | 209.6 ± 205.7 | 175 ± 16 | 53 | 0.1 | 0.000 | 11 |
| cal | above | 250 | admission | 57 | 138.9 ± 17.2 | 213.0 ± 19.6 | 187 ± 2 | 0 | 118.7 | 0.000 | 0 |
| cal | above | 250 | admission | 76 | 118.3 ± 15.5 | 182.2 ± 17.6 | 195 ± 3 | 1 | 93.7 | 0.000 | 0 |
| cal | above | 250 | admission | 95 | 117.0 ± 20.0 | 182.2 ± 23.0 | 197 ± 5 | 56 | 87.2 | 0.000 | 0 |
| cal | above | 250 | both | 57 | 138.9 ± 17.2 | 213.0 ± 19.6 | 187 ± 2 | 0 | 118.7 | 0.000 | 0 |
| cal | above | 250 | both | 76 | 118.3 ± 15.6 | 182.1 ± 17.5 | 195 ± 3 | 2 | 93.7 | 0.000 | 0 |
| cal | above | 250 | both | 95 | 112.7 ± 17.3 | 176.5 ± 20.6 | 199 ± 4 | 92 | 83.5 | 0.000 | 0 |
| cal | above | 250 | priority | - | 419.7 ± 53.5 | 691.4 ± 52.0 | 111 ± 5 | 716 | 0.1 | 0.000 | 1 |
| cal | above | 250 | stock | - | 725.5 ± 96.6 | 1208.3 ± 30.7 | 73 ± 5 | 37 | 0.1 | 0.000 | 659 |
| g3 | below | 140 | admission | 58 | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | admission | 77 | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | admission | 96 | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | both | 58 | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | both | 77 | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | both | 96 | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | priority | - | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | stock | - | 5.8 ± 0.3 | 16.4 ± 0.8 | 142 ± 3 | 0 | 0.0 | 0.000 | 0 |
| g3 | at | 230 | admission | 58 | 17.5 ± 4.1 | 39.6 ± 5.4 | 230 ± 4 | 0 | 5.1 | 0.000 | 0 |
| g3 | at | 230 | admission | 77 | 13.1 ± 1.7 | 36.3 ± 3.1 | 232 ± 3 | 0 | 0.5 | 0.000 | 0 |
| g3 | at | 230 | admission | 96 | 12.8 ± 1.4 | 36.7 ± 3.8 | 233 ± 3 | 2 | 0.1 | 0.000 | 0 |
| g3 | at | 230 | both | 58 | 17.5 ± 4.1 | 39.6 ± 5.4 | 230 ± 4 | 0 | 5.1 | 0.000 | 0 |
| g3 | at | 230 | both | 77 | 13.1 ± 1.7 | 36.3 ± 3.2 | 232 ± 3 | 0 | 0.5 | 0.000 | 0 |
| g3 | at | 230 | both | 96 | 12.7 ± 1.3 | 36.5 ± 3.5 | 233 ± 3 | 2 | 0.1 | 0.000 | 0 |
| g3 | at | 230 | priority | - | 13.2 ± 2.3 | 43.6 ± 19.0 | 230 ± 6 | 167 | 0.0 | 0.000 | 0 |
| g3 | at | 230 | stock | - | 13.3 ± 2.5 | 59.2 ± 53.8 | 228 ± 10 | 24 | 0.0 | 0.000 | 1 |
| g3 | above | 300 | admission | 58 | 117.4 ± 13.3 | 178.5 ± 17.0 | 233 ± 3 | 0 | 101.3 | 0.000 | 0 |
| g3 | above | 300 | admission | 77 | 93.7 ± 11.6 | 141.6 ± 14.9 | 247 ± 4 | 0 | 73.7 | 0.000 | 0 |
| g3 | above | 300 | admission | 96 | 95.6 ± 17.4 | 146.0 ± 20.8 | 249 ± 7 | 89 | 70.8 | 0.000 | 0 |
| g3 | above | 300 | both | 58 | 117.4 ± 13.3 | 178.5 ± 17.0 | 233 ± 3 | 0 | 101.3 | 0.000 | 0 |
| g3 | above | 300 | both | 77 | 93.7 ± 11.6 | 141.6 ± 14.9 | 247 ± 4 | 1 | 73.7 | 0.000 | 0 |
| g3 | above | 300 | both | 96 | 89.7 ± 14.9 | 137.3 ± 17.7 | 251 ± 5 | 114 | 65.4 | 0.000 | 0 |
| g3 | above | 300 | priority | - | 459.9 ± 51.9 | 749.1 ± 55.5 | 126 ± 3 | 866 | 0.1 | 0.000 | 3 |
| g3 | above | 300 | stock | - | 808.9 ± 90.2 | 1229.0 ± 26.4 | 80 ± 6 | 38 | 0.1 | 0.000 | 889 |

## Policies, 30-min window (mean ± sd over 5 seeds)

| model | rate | lambda | policy | K | p50 s | p95 s | thr/min | preempt | queue wait mean s | idle | unfinished |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cal | below | 110 | admission | 76 | 5.9 ± 0.2 | 17.4 ± 0.5 | 111 ± 1 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | both | 76 | 5.9 ± 0.2 | 17.4 ± 0.5 | 111 ± 1 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | priority | - | 5.9 ± 0.2 | 17.4 ± 0.5 | 111 ± 1 | 0 | 0.0 | 0.000 | 0 |
| cal | below | 110 | stock | - | 5.9 ± 0.2 | 17.4 ± 0.5 | 111 ± 1 | 0 | 0.0 | 0.000 | 0 |
| cal | at | 190 | admission | 76 | 21.0 ± 2.8 | 54.2 ± 3.9 | 191 ± 1 | 1 | 3.9 | 0.000 | 0 |
| cal | at | 190 | both | 76 | 21.0 ± 2.8 | 54.2 ± 3.9 | 191 ± 1 | 1 | 3.9 | 0.000 | 0 |
| cal | at | 190 | priority | - | 194.6 ± 232.4 | 576.0 ± 391.2 | 153 ± 27 | 1367 | 0.1 | 0.000 | 0 |
| cal | at | 190 | stock | - | 499.1 ± 443.4 | 1708.1 ± 1032.2 | 126 ± 42 | 106 | 0.1 | 0.000 | 599 |
| cal | above | 250 | admission | 76 | 304.4 ± 3.9 | 516.8 ± 23.9 | 197 ± 2 | 2 | 275.0 | 0.000 | 0 |
| cal | above | 250 | both | 76 | 304.1 ± 3.9 | 516.3 ± 23.4 | 197 ± 2 | 3 | 274.8 | 0.000 | 0 |
| cal | above | 250 | priority | - | 1260.2 ± 20.1 | 1998.0 ± 34.4 | 111 ± 2 | 1942 | 0.1 | 0.000 | 1046 |
| cal | above | 250 | stock | - | 1916.3 ± 16.3 | 2968.3 ± 22.2 | 72 ± 2 | 38 | 0.1 | 0.000 | 3431 |
| g3 | below | 140 | admission | 77 | 5.7 ± 0.1 | 16.4 ± 0.2 | 141 ± 1 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | both | 77 | 5.7 ± 0.1 | 16.4 ± 0.2 | 141 ± 1 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | priority | - | 5.7 ± 0.1 | 16.4 ± 0.2 | 141 ± 1 | 0 | 0.0 | 0.000 | 0 |
| g3 | below | 140 | stock | - | 5.7 ± 0.1 | 16.4 ± 0.2 | 141 ± 1 | 0 | 0.0 | 0.000 | 0 |
| g3 | at | 230 | admission | 77 | 12.6 ± 0.4 | 36.1 ± 1.0 | 231 ± 1 | 0 | 0.6 | 0.000 | 0 |
| g3 | at | 230 | both | 77 | 12.6 ± 0.4 | 36.1 ± 1.0 | 231 ± 1 | 0 | 0.6 | 0.000 | 0 |
| g3 | at | 230 | priority | - | 89.6 ± 159.9 | 421.0 ± 354.7 | 198 ± 29 | 1150 | 0.1 | 0.000 | 0 |
| g3 | at | 230 | stock | - | 177.4 ± 355.2 | 1092.3 ± 994.3 | 183 ± 44 | 63 | 0.1 | 0.000 | 346 |
| g3 | above | 300 | admission | 77 | 231.5 ± 5.8 | 399.2 ± 17.5 | 249 ± 3 | 2 | 211.9 | 0.000 | 0 |
| g3 | above | 300 | both | 77 | 231.3 ± 5.6 | 399.0 ± 17.2 | 250 ± 3 | 4 | 211.8 | 0.000 | 0 |
| g3 | above | 300 | priority | - | 1366.3 ± 28.4 | 2074.6 ± 30.5 | 126 ± 2 | 2160 | 0.1 | 0.000 | 1654 |
| g3 | above | 300 | stock | - | 1975.8 ± 12.8 | 3015.1 ± 19.3 | 80 ± 2 | 35 | 0.1 | 0.000 | 4462 |

## Caveats

- g1_fidelity.csv: sim within ±14% of real vLLM above the KV limit but underestimates resume latency below it.
- Trace recorded at concurrency 8: only token counts and tool times are used; per-turn off-GPU overhead fixed at 15 ms (c = 8 median; real grows to ~60 ms at c = 64).
- The g3 model is ~25% optimistic at c = 64 in closed loop (iteration time 52 vs 69 ms real); cal fixes that by fiat (one factor, three points).
- p50/p95 are over tasks arriving in the window; tasks unfinished at the end of the drain count with their elapsed time (lower bound).
- Preemption = full recompute; vLLM may get some prefix hits back. Admission order inside vLLM stops at the first request that can't fit.

## Reading (written after the run)

- Stock has a cliff, not a slope: past ~230/min (g3) / ~190/min (cal) the vLLM waiting queue grows, waiting
  requests' prefixes get evicted (LRU), every resumed turn re-prefills its whole context, and throughput
  collapses to ~70-80/min (close to the real caching-off cell: c = 64 explore, caching off, ~64 tasks/min).
  The "at" rate is metastable: some seeds collapse inside the window (hence stock's large sd there).
- Admission at K ~ 77 sits at the closed-loop throughput peak (N = 80-96), so it holds ~max throughput above
  capacity; its task time there is mostly gateway queue wait, which grows with window length (8 vs 30 min).
- GPU idle fraction under admission is 0.000 at every rate: explore pauses are ~15 ms, so K tasks always
  have work. Priority alone avoids part of the collapse but preempts heavily.
- Recommended rates for the GPU runs: the **cal** set (110 / 190 / 250 per min), because cal matches the real
  closed-loop cells at c = 8/32/64 within ~6% on p50 (g3 is 15-25% optimistic at c >= 32). Under g3's set
  (140 / 230 / 300), 230 would likely already be above real capacity.
- Over-capacity stock p95s are lower bounds (tasks unfinished after the 15-min drain count at elapsed time).
