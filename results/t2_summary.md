# Test 2: real SQL-agent traces (BIRD dev, 150 tasks, seed 0)

**Rule DB** (concurrency 1): DB share = 3.6% (≥ 40% means come back) → **DROP broker + result caching**

**Rule D4** (concurrency 1): 87% of the 15 tasks above p90 are wrong (≥ 60% pursue, < 40% drop) → **PURSUE D4 early stopping**

### concurrency 1 (n = 150)

- accuracy 34.0% ± 3.9 (SE); mean turns 6.09; task time p50 2.72 s, p90 4.70 s, p95 5.14 s; mean prompt tokens/task 4655
- time shares of Σ task time (452 s): **DB 3.6%**, LLM queue 0.0%, prefill 3.8%, decode 90.3%, other LLM-call 2.2%, agent/other 0.1%
- tasks above p90 (15): **87% wrong**
- exploring: 53.5% of turns (all tool calls are exploration tools), 63.9% of tool calls
- DB time from repeated SQL (total DB 16.2 s): exact within-task 0.7%, canonical within-task 0.7%, exact across tasks (same DB) 5.2%, canonical across 5.2%
- task status {'answered': 107, 'no_sql': 42, 'max_turns': 1}; tool errors {'no_such_column': 71, 'no_such_table': 38, 'syntax': 12, 'operational': 4}

### concurrency 8 (n = 150)

- accuracy 36.0% ± 3.9 (SE); mean turns 6.10; task time p50 2.91 s, p90 5.08 s, p95 5.50 s; mean prompt tokens/task 4680
- time shares of Σ task time (480 s): **DB 1.1%**, LLM queue 0.0%, prefill 5.6%, decode 90.9%, other LLM-call 2.4%, agent/other 0.1%
- tasks above p90 (15): **87% wrong**
- exploring: 53.6% of turns (all tool calls are exploration tools), 64.0% of tool calls
- DB time from repeated SQL (total DB 5.2 s): exact within-task 2.4%, canonical within-task 2.4%, exact across tasks (same DB) 17.0%, canonical across 17.0%
- task status {'answered': 107, 'no_sql': 42, 'max_turns': 1}; tool errors {'no_such_table': 37, 'no_such_column': 70, 'syntax': 11, 'operational': 4}

