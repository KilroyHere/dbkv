# calib: EXPLAIN vs runtime on DuckDB (TPC-H, TPC-DS). Gate G2.

A closed direction (D3), kept for G2. Results: `results/g2_sf10_summary.md`, `results/g2_sf100_summary.md`, figure `results/fig_g2_explain.png`.

- `g2_queries.py`: query generator. TPC-H 22 templates with qgen-range parameters; TPC-DS
  `tpcds_queries()` with year/month shifts; agent-like probes (point, range, groupby, count, join,
  topk, like) built from schema stats, one template per probe family.
- `g2_run.py`: times `EXPLAIN (FORMAT JSON)`, parses per-operator "Estimated Cardinality", then runs
  each query (1 warm-up + 3 timed, 60 s timeout via `con.interrupt()`, censored) under
  `memory_limit=16GB`, `threads=8`. One CSV row per query in `$DBKV_DATA/runs/g2/<run_id>/results.csv`.
- `g2_analyze.py <run_dir>`: Spearman rho, 3-class accuracy (0.25 s / 2 s), EXPLAIN regressor vs
  per-template history vs global median, leave-one-template-out and random 5-fold. Writes
  `summary.json`, `summary.md`.
- `g2_sf10.sbatch` / `g2_sf100.sbatch`: full runs on TPC-H SF10 (+ TPC-DS SF10 if present) and SF100. Compute nodes only.
