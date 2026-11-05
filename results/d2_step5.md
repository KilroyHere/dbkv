# D2 step 5: brief arms on BIRD dev (frozen agent 220001e, concurrency 8)

| arm | n | turns | p50 s | p95 s | accuracy | Δacc vs full (paired SE) | Δacc vs explore (paired SE) | prompt tok/task | no-SQL | build p50 s |
|---|---|---|---|---|---|---|---|---|---|---|
| explore | 1534 | 7.45 | 4.04 | 12.51 | 43.5% | -6.9 (1.1) | +0.0 (0.0) | 10387 | 0.0% | 0.00 |
| full | 1534 | 6.15 | 4.39 | 15.55 | 50.4% | +0.0 (0.0) | +6.9 (1.1) | 34256 | 0.0% | 0.00 |
| compact | 1534 | 6.18 | 3.81 | 11.83 | 50.7% | +0.3 (0.9) | +7.2 (1.1) | 15409 | 0.0% | 0.00 |
| lexical | 1534 | 6.04 | 3.76 | 12.08 | 49.3% | -1.1 (1.0) | +5.8 (1.1) | 10146 | 0.0% | 0.00 |
| llm | 1534 | 5.97 | 4.16 | 13.72 | 49.0% | -1.4 (1.1) | +5.5 (1.1) | 8572 | 0.0% | 0.46 |
| oracle | 1534 | 5.34 | 3.61 | 11.26 | 58.3% | +7.9 (1.1) | +14.8 (1.2) | 8504 | 0.0% | 0.00 |

## Rules (PLAN §2c)

- **compact**: retention 0.60 (≥ 0.60: yes); Δacc vs full +0.3 ± 0.9 (≥ −2.0: yes); p95 11.83 vs explore 12.51 (≤: yes) → **R1 PASS**; prompt tokens 15409 vs 0.5 × full = 17128 → **R2 PASS**
- **lexical**: retention 0.67 (≥ 0.60: yes); Δacc vs full -1.1 ± 1.0 (≥ −2.0: yes); p95 12.08 vs explore 12.51 (≤: yes) → **R1 PASS**; prompt tokens 10146 vs 0.5 × full = 17128 → **R2 PASS**
- **llm**: retention 0.70 (≥ 0.60: yes); Δacc vs full -1.4 ± 1.1 (≥ −2.0: yes); p95 13.72 vs explore 12.51 (≤: no) → **R1 FAIL**; prompt tokens 8572 vs 0.5 × full = 17128 → **R2 PASS**

**Research question at concurrency 8: YES** (arms passing R1 and R2: compact, lexical).
