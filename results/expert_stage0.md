# Expert Stage 0: failed SQL + repair turns, and wrong-answer types (existing traces)

Definitions: docs/EXPERT.md (pre-registered). *Failed* = turn issuing a failed `execute_sql`; *repair* = the turn right after one; *union* = either.

| arm | n | acc | turns | failed-SQL turns | repair turns | failed ∪ repair | decode s in failed / repair / ∪ | invented-name errs / task |
|---|---|---|---|---|---|---|---|---|
| T2 plain c=1 | 150 | 34.0% | 913 | 13.5% | **13.5%** | 25.7% | 19.9% / 10.1% / 28.0% | 0.71 |
| T2/T3(a) plain c=8 | 150 | 36.0% | 915 | 13.1% | **13.1%** | 25.1% | 19.5% / 9.8% / 27.6% | 0.70 |
| T3(b) full c=8 | 150 | 43.3% | 462 | 9.7% | **9.7%** | 17.3% | 10.4% / 7.0% / 15.1% | 0.23 |
| T3(c) oracle c=8 | 150 | 54.0% | 444 | 7.7% | **7.7%** | 14.0% | 8.2% / 4.9% / 12.0% | 0.14 |
| fixed agent 779bcfd plain c=8 (aside) | 150 | 44.7% | 1084 | 4.1% | **4.1%** | 7.2% | 5.8% / 6.2% / 10.8% | 0.19 |

**Wrong answers by type** (no SQL → invented names → other SQL error → wrong logic, first match):

| arm | wrong | no SQL | invented names | other SQL error | wrong logic (of which had invented-name errs earlier) | SQL-writing share | wrong w/o ```sql``` block |
|---|---|---|---|---|---|---|---|
| T2 plain c=1 | 99 | 22 | 0 | 4 | 73 (28) | 78% | 42 |
| T2/T3(a) plain c=8 | 96 | 21 | 0 | 2 | 73 (29) | 78% | 42 |
| T3(b) full c=8 | 85 | 10 | 0 | 4 | 71 (13) | 88% | 24 |
| T3(c) oracle c=8 | 69 | 6 | 0 | 2 | 61 (7) | 91% | 16 |
| fixed agent 779bcfd plain c=8 (aside) | 83 | 5 | 0 | 3 | 75 (11) | 94% | 11 |

Failed `execute_sql` calls by class: T2 plain c=1: {'no_such_column': 71, 'no_such_table': 36, 'syntax': 12, 'operational': 4}; T2/T3(a) plain c=8: {'no_such_column': 70, 'no_such_table': 35, 'syntax': 11, 'operational': 4}; T3(b) full c=8: {'no_such_column': 35, 'operational': 2, 'syntax': 8}; T3(c) oracle c=8: {'operational': 3, 'timeout': 3, 'syntax': 7, 'no_such_column': 21}; fixed agent 779bcfd plain c=8 (aside): {'no_such_column': 26, 'no_such_table': 2, 'syntax': 14, 'operational': 2}

**Stage 0 rule** (pooled over T3(b) full c=8,T3(c) oracle c=8): repair turns = 8.7% of turns (stop needs < 15%: yes); SQL-writing errors = 90% of 154 wrong answers (stop needs ≤ 50%: no) → **CONTINUE to Stage 1**

