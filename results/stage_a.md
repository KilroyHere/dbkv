# Stage A: brief-aware prompt (150 questions, concurrency 8, lexical briefs)

| run | n | turns | p50 s | p95 s | accuracy | Δacc vs ref (paired SE) | no-SQL | prompt tok/task | describe/task | describe on brief tables/task | nudged turns/task | turns after 1st OK SQL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| (1) frozen | 150 | 5.57 | 3.88 | 13.54 | 46.0% | +0.0 (0.0) | 0.0% | 8918 | 2.22 | 2.17 | 0.69 | 1.85 |
| (2) aware | 150 | 5.67 | 3.54 | 14.38 | 44.0% | -2.0 (2.6) | 0.7% | 9024 | 0.65 | 0.64 | 2.52 | 3.44 |
| (3) aware+desc | 150 | 4.53 | 3.16 | 10.88 | 43.3% | -2.7 (3.0) | 0.0% | 7296 | 0.71 | 0.69 | 1.29 | 2.45 |

## Stage A gate (vs (1) frozen): describe-on-brief ≤ 0.3/task, no-SQL < 5%, accuracy ≥ ref − 3 points

- **(2) aware**: describe-on-brief 0.64 (FAIL), no-SQL 0.7% (ok), Δacc -2.0 (ok) → **FAIL**
- **(3) aware+desc**: describe-on-brief 0.69 (FAIL), no-SQL 0.0% (ok), Δacc -2.7 (ok) → **FAIL**

**Stage A: FAIL (neither passes)**
