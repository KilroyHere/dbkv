# Test 3: D2 pilot, schema brief (concurrency 8, 150 tasks)

| arm | turns/task | p50 task s | p95 task s | accuracy ± SE | prompt tokens/task | explore turns |
|---|---|---|---|---|---|---|
| (a) plain exploration | 6.10 | 2.91 | 5.50 | 36.0% ± 3.9 | 4680 | 53.6% |
| (b) full schema + 3 samples | 3.08 | 2.48 | 6.80 | 43.3% ± 4.0 | 8632 | 20.8% |
| (c) oracle brief (gold tables/columns) | 2.96 | 2.18 | 5.03 | 54.0% ± 4.1 | 2827 | 21.2% |

**Rule** (all three needed to pursue):
1. explore share (a) = 53.6% ≥ 30%: yes
2. turns (c) = 2.96 ≤ 0.75 × (a) = 4.57: yes (cut 51.5%)
3. p50 (b) = 2.48 s > 1.05 × p50 (c) = 2.28 s: yes

**→ PURSUE D2**

### (a) plain exploration (n = 150)

- accuracy 36.0% ± 3.9 (SE); mean turns 6.10; task time p50 2.91 s, p90 5.08 s, p95 5.50 s; mean prompt tokens/task 4680
- time shares of Σ task time (480 s): **DB 1.1%**, LLM queue 0.0%, prefill 5.6%, decode 90.9%, other LLM-call 2.4%, agent/other 0.1%
- tasks above p90 (15): **87% wrong**
- exploring: 53.6% of turns (all tool calls are exploration tools), 64.0% of tool calls
- DB time from repeated SQL (total DB 5.2 s): exact within-task 2.4%, canonical within-task 2.4%, exact across tasks (same DB) 17.0%, canonical across 17.0%
- task status {'answered': 107, 'no_sql': 42, 'max_turns': 1}; tool errors {'no_such_table': 37, 'no_such_column': 70, 'syntax': 11, 'operational': 4}

### (b) full schema + 3 samples (n = 150)

- accuracy 43.3% ± 4.0 (SE); mean turns 3.08; task time p50 2.48 s, p90 5.72 s, p95 6.80 s; mean prompt tokens/task 8632
- time shares of Σ task time (463 s): **DB 5.9%**, LLM queue 0.0%, prefill 4.6%, decode 84.3%, other LLM-call 1.7%, agent/other 3.5%
- tasks above p90 (15): **80% wrong**
- exploring: 20.8% of turns (all tool calls are exploration tools), 30.8% of tool calls
- DB time from repeated SQL (total DB 27.2 s): exact within-task 0.0%, canonical within-task 0.0%, exact across tasks (same DB) 0.3%, canonical across 0.3%
- task status {'answered': 117, 'no_sql': 33}; tool errors {'no_such_column': 35, 'operational': 2, 'syntax': 8}

### (c) oracle brief (gold tables/columns) (n = 150)

- accuracy 54.0% ± 4.1 (SE); mean turns 2.96; task time p50 2.18 s, p90 4.17 s, p95 5.03 s; mean prompt tokens/task 2827
- time shares of Σ task time (564 s): **DB 32.9%**, LLM queue 0.0%, prefill 3.7%, decode 62.1%, other LLM-call 1.2%, agent/other 0.0%
- tasks above p90 (15): **73% wrong**
- exploring: 21.2% of turns (all tool calls are exploration tools), 32.0% of tool calls
- DB time from repeated SQL (total DB 185.6 s): exact within-task 65.1%, canonical within-task 65.1%, exact across tasks (same DB) 65.1%, canonical across 65.1%
- task status {'answered': 122, 'no_sql': 28}; tool errors {'operational': 3, 'syntax': 7, 'no_such_column': 21, 'timeout': 3}

