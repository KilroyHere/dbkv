# Expert Stage 1.3 (`/pscratch/sd/a/ap2568/dbkv/runs/expert/60873555`)

| arm | brief | acc ± SE | Δacc vs (a) ± paired SE | turns/task | repair/task | adapter calls/task | invented errs/task | output tok/task (agent + adapter) | prefill (uncached) tok/task (agent + adapter) | prompt tok/task | p50 / p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| (a) base | full | 46.7% ± 4.1 | — | 6.28 | 0.29 | 0.00 | 0.19 | 322 (322 + 0) | 1568 (1568 + 0) | 23236 | 4.32 / 13.09 |
| (a) base | oracle | 53.3% ± 4.1 | — | 5.83 | 0.19 | 0.00 | 0.10 | 271 (271 + 0) | 1796 (1796 + 0) | 8977 | 4.01 / 13.00 |
| (b) +3 few-shot | full | 48.0% ± 4.1 | +1.3 ± 3.0 | 7.67 | 0.15 | 0.00 | 0.10 | 305 (305 + 0) | 2016 (2016 + 0) | 34929 | 5.69 / 14.47 |
| (b) +3 few-shot | oracle | 52.0% ± 4.1 | -1.3 ± 3.1 | 7.27 | 0.20 | 0.00 | 0.07 | 283 (283 + 0) | 2223 (2223 + 0) | 18526 | 4.75 / 12.39 |
| (d) write_sql expert | full | 48.0% ± 4.1 | +1.3 ± 3.7 | 5.37 | 0.49 | 1.42 | 0.42 | 527 (244 + 283) | 3577 (1422 + 2155) | 23563 | 8.58 / 34.31 |
| (d) write_sql expert | oracle | 56.0% ± 4.1 | +2.7 ± 3.8 | 5.07 | 0.65 | 1.60 | 0.59 | 556 (249 + 307) | 1927 (1627 + 300) | 10434 | 7.07 / 35.03 |

**Wrong answers by type** (no SQL → invented names → other SQL error → wrong logic):

| arm | brief | wrong | no SQL | invented | other SQL err | wrong logic | status | adapter: no SQL / exec fail |
|---|---|---|---|---|---|---|---|---|
| (a) base | full | 80 | 0 | 0 | 7 | 73 | {'answered': 149, 'no_sql': 1} | 0 / 0 |
| (a) base | oracle | 70 | 0 | 0 | 5 | 65 | {'answered': 150} | 0 / 0 |
| (b) +3 few-shot | full | 78 | 1 | 0 | 9 | 68 | {'answered': 148, 'no_sql': 2} | 0 / 0 |
| (b) +3 few-shot | oracle | 72 | 0 | 0 | 5 | 67 | {'answered': 150} | 0 / 0 |
| (d) write_sql expert | full | 78 | 1 | 0 | 3 | 74 | {'answered': 149, 'no_sql': 1} | 0 / 73 |
| (d) write_sql expert | oracle | 66 | 0 | 0 | 3 | 63 | {'answered': 150} | 0 / 97 |

**Pooled over both briefs (300 task-runs per arm)**

- (a) base: acc 50.0%, turns/task 6.05, invented errs/task 0.15, p50 4.13 s
- (b) +3 few-shot: acc 50.0%, turns/task 7.47, invented errs/task 0.09, p50 5.18 s
- (d) write_sql expert: acc 52.0%, turns/task 5.22, invented errs/task 0.50, p50 7.70 s

**Predictions** ((d) vs (a), same brief; per brief and pooled):

- full: (1) Δacc +1.3 ± 3.7 pts (≥ +8: not met); (2) invented errs 0.19 → 0.42, cut -117% (≥ 50%: not met); (3) turns 6.28 → 5.37, cut 14.5% (≥ 15%: not met); (4) p50 4.32 → 8.58 s, cut -98.4% (≥ 10%: not met)
- oracle: (1) Δacc +2.7 ± 3.8 pts (≥ +8: not met); (2) invented errs 0.10 → 0.59, cut -487% (≥ 50%: not met); (3) turns 5.83 → 5.07, cut 12.9% (≥ 15%: not met); (4) p50 4.01 → 7.07 s, cut -76.2% (≥ 10%: not met)
- pooled: (1) Δacc +2.0 ± 2.6 pts (≥ +8: not met); (2) invented errs 0.15 → 0.50, cut -243% (≥ 50%: not met); (3) turns 6.05 → 5.22, cut 13.8% (≥ 15%: not met); (4) p50 4.13 → 7.70 s, cut -86.7% (≥ 10%: not met)

**Stage 1 rule** (pooled): vs (a) base: Δacc +2.0 pts (≥ 5?), turns cut 13.8% (≥ 10%?) → beats; vs (b) +3 few-shot: Δacc +2.0 pts (≥ 5?), turns cut 30.1% (≥ 10%?) → beats → **CONTINUE past Stage 1**

