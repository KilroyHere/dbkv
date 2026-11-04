# G2 EXPLAIN calibration: run `60825416`

Classes: short < 0.25 s <= medium < 2.0 s <= long. Median of timed runs; timeouts censored at the timeout (long class). Predictors fit per database.

## tpcds_sf10: 890 queries, 106 templates, 0 censored

runtime s: min 0.000372, p10 0.0008347, p50 0.01291, p90 0.1107, p99 0.6979, max 1.577
  
class counts: {'short': 854, 'medium': 36, 'long': 0}  
EXPLAIN latency: mean 2.93 ms, p50 1.54, p99 15.82 (repeat call mean 2.51)

Spearman rho, single EXPLAIN feature vs runtime: scan_ec_sum 0.851, sum_ec 0.846, max_ec 0.844, scan_base_rows 0.844, max_base_rows 0.828, logsum_ec 0.821  
mean within-template rho (max_ec): 0.7197187736545295

| split | predictor | acc | rho | MAE log10 | confusion (rows true s/m/l) |
|---|---|---|---|---|---|
| loto | explain | 0.956 | 0.846 | 0.393 | [[836, 18, 0], [21, 15, 0], [0, 0, 0]] |
| loto | explain1 | 0.956 | 0.805 | 0.509 | [[848, 6, 0], [29, 3, 4], [0, 0, 0]] |
| loto | history | 0.960 | nan | 0.811 | [[854, 0, 0], [36, 0, 0], [0, 0, 0]] |
| loto | global | 0.960 | nan | 0.811 | [[854, 0, 0], [36, 0, 0], [0, 0, 0]] |
| random | explain | 0.965 | 0.879 | 0.324 | [[845, 9, 0], [22, 14, 0], [0, 0, 0]] |
| random | explain1 | 0.956 | 0.835 | 0.457 | [[848, 6, 0], [29, 3, 4], [0, 0, 0]] |
| random | history | 0.985 | 0.823 | 0.301 | [[850, 4, 0], [9, 27, 0], [0, 0, 0]] |
| random | global | 0.960 | nan | 0.759 | [[854, 0, 0], [36, 0, 0], [0, 0, 0]] |

## tpch_sf10: 934 queries, 29 templates, 0 censored

runtime s: min 0.000369, p10 0.001392, p50 0.03885, p90 0.2305, p99 0.689, max 14.4
  
class counts: {'short': 851, 'medium': 81, 'long': 2}  
EXPLAIN latency: mean 2.34 ms, p50 1.83, p99 7.16 (repeat call mean 1.80)

Spearman rho, single EXPLAIN feature vs runtime: sum_ec 0.813, max_ec 0.801, scan_ec_sum 0.799, scan_base_rows 0.769, logsum_ec 0.750, max_base_rows 0.715  
mean within-template rho (max_ec): 0.5423684979850398

| split | predictor | acc | rho | MAE log10 | confusion (rows true s/m/l) |
|---|---|---|---|---|---|
| loto | explain | 0.894 | 0.778 | 0.408 | [[830, 21, 0], [76, 5, 0], [1, 1, 0]] |
| loto | explain1 | 0.911 | 0.735 | 0.534 | [[851, 0, 0], [81, 0, 0], [0, 2, 0]] |
| loto | history | 0.911 | nan | 0.768 | [[851, 0, 0], [81, 0, 0], [2, 0, 0]] |
| loto | global | 0.911 | nan | 0.768 | [[851, 0, 0], [81, 0, 0], [2, 0, 0]] |
| random | explain | 0.931 | 0.852 | 0.323 | [[850, 1, 0], [61, 20, 0], [2, 0, 0]] |
| random | explain1 | 0.911 | 0.792 | 0.441 | [[851, 0, 0], [81, 0, 0], [0, 2, 0]] |
| random | history | 0.953 | 0.814 | 0.302 | [[851, 0, 0], [42, 39, 0], [2, 0, 0]] |
| random | global | 0.911 | nan | 0.694 | [[851, 0, 0], [81, 0, 0], [2, 0, 0]] |

## pooled: 1824 queries, 128 templates, 0 censored

runtime s: min 0.000369, p10 0.0009603, p50 0.02374, p90 0.1761, p99 0.7039, max 14.4
  
class counts: {'short': 1705, 'medium': 117, 'long': 2}  
EXPLAIN latency: mean 2.63 ms, p50 1.68, p99 12.97 (repeat call mean 2.15)

Spearman rho, single EXPLAIN feature vs runtime: sum_ec 0.839, scan_ec_sum 0.823, max_ec 0.819, scan_base_rows 0.803, logsum_ec 0.773, max_base_rows 0.771  
mean within-template rho (max_ec): 0.6985870199771238

| split | predictor | acc | rho | MAE log10 | confusion (rows true s/m/l) |
|---|---|---|---|---|---|
| loto | explain | 0.924 | 0.823 | 0.400 | [[1666, 39, 0], [97, 20, 0], [1, 1, 0]] |
| loto | explain1 | 0.933 | 0.763 | 0.522 | [[1699, 6, 0], [110, 3, 4], [0, 2, 0]] |
| loto | history | 0.935 | nan | 0.789 | [[1705, 0, 0], [117, 0, 0], [2, 0, 0]] |
| loto | global | 0.935 | nan | 0.789 | [[1705, 0, 0], [117, 0, 0], [2, 0, 0]] |
| random | explain | 0.948 | 0.870 | 0.324 | [[1695, 10, 0], [83, 34, 0], [2, 0, 0]] |
| random | explain1 | 0.933 | 0.791 | 0.449 | [[1699, 6, 0], [110, 3, 4], [0, 2, 0]] |
| random | history | 0.969 | 0.838 | 0.302 | [[1701, 4, 0], [51, 66, 0], [2, 0, 0]] |
| random | global | 0.935 | nan | 0.725 | [[1705, 0, 0], [117, 0, 0], [2, 0, 0]] |

## Kill rule (PLAN §3 G2)

- rho(EXPLAIN regressor, LOTO, pooled) = 0.823 (kill if < 0.5)
- LOTO acc EXPLAIN 0.924 vs history 0.935; MAE log10 0.400 vs 0.789
- **killed: True** (rho < 0.5, or LOTO accuracy not above history)
- classes degenerate (>=95% in one class; accuracy test uninformative): False
