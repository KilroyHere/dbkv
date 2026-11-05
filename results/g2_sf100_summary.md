# G2 EXPLAIN calibration: run `60826277`

Classes: short < 0.25 s <= medium < 2.0 s <= long. Median of timed runs; timeouts censored at the timeout (long class). Predictors fit per database.

## tpch_sf100: 707 queries, 29 templates, 3 censored

runtime s: min 0.000359, p10 0.002148, p50 0.3933, p90 2.763, p99 14.21, max 60
  
class counts: {'short': 308, 'medium': 307, 'long': 92}  
EXPLAIN latency: mean 9.07 ms, p50 3.01, p99 120.39 (repeat call mean 2.07)

Spearman rho, single EXPLAIN feature vs runtime: sum_ec 0.834, scan_ec_sum 0.804, max_ec 0.793, scan_base_rows 0.785, logsum_ec 0.770, max_base_rows 0.734  
mean within-template rho (max_ec): 0.6105555823120684

| split | predictor | acc | rho | MAE log10 | confusion (rows true s/m/l) |
|---|---|---|---|---|---|
| loto | explain | 0.686 | 0.826 | 0.539 | [[262, 46, 0], [61, 190, 56], [7, 52, 33]] |
| loto | explain1 | 0.687 | 0.741 | 0.779 | [[184, 124, 0], [7, 300, 0], [0, 90, 2]] |
| loto | history | 0.434 | nan | 1.079 | [[0, 308, 0], [0, 307, 0], [0, 92, 0]] |
| loto | global | 0.434 | nan | 1.079 | [[0, 308, 0], [0, 307, 0], [0, 92, 0]] |
| random | explain | 0.823 | 0.872 | 0.431 | [[287, 21, 0], [38, 245, 24], [7, 35, 50]] |
| random | explain1 | 0.720 | 0.791 | 0.634 | [[212, 96, 0], [12, 295, 0], [0, 90, 2]] |
| random | history | 0.850 | 0.797 | 0.451 | [[283, 25, 0], [32, 272, 3], [17, 29, 46]] |
| random | global | 0.434 | nan | 0.981 | [[0, 308, 0], [0, 307, 0], [0, 92, 0]] |

## pooled: 707 queries, 29 templates, 3 censored

runtime s: min 0.000359, p10 0.002148, p50 0.3933, p90 2.763, p99 14.21, max 60
  
class counts: {'short': 308, 'medium': 307, 'long': 92}  
EXPLAIN latency: mean 9.07 ms, p50 3.01, p99 120.39 (repeat call mean 2.07)

Spearman rho, single EXPLAIN feature vs runtime: sum_ec 0.834, scan_ec_sum 0.804, max_ec 0.793, scan_base_rows 0.785, logsum_ec 0.770, max_base_rows 0.734  
mean within-template rho (max_ec): 0.6105555823120684

| split | predictor | acc | rho | MAE log10 | confusion (rows true s/m/l) |
|---|---|---|---|---|---|
| loto | explain | 0.686 | 0.826 | 0.539 | [[262, 46, 0], [61, 190, 56], [7, 52, 33]] |
| loto | explain1 | 0.687 | 0.741 | 0.779 | [[184, 124, 0], [7, 300, 0], [0, 90, 2]] |
| loto | history | 0.434 | nan | 1.079 | [[0, 308, 0], [0, 307, 0], [0, 92, 0]] |
| loto | global | 0.434 | nan | 1.079 | [[0, 308, 0], [0, 307, 0], [0, 92, 0]] |
| random | explain | 0.823 | 0.872 | 0.431 | [[287, 21, 0], [38, 245, 24], [7, 35, 50]] |
| random | explain1 | 0.720 | 0.791 | 0.634 | [[212, 96, 0], [12, 295, 0], [0, 90, 2]] |
| random | history | 0.850 | 0.797 | 0.451 | [[283, 25, 0], [32, 272, 3], [17, 29, 46]] |
| random | global | 0.434 | nan | 0.981 | [[0, 308, 0], [0, 307, 0], [0, 92, 0]] |

## Kill rule (PLAN §3 G2)

- rho(EXPLAIN regressor, LOTO, pooled) = 0.826 (kill if < 0.5)
- LOTO acc EXPLAIN 0.686 vs history 0.434; MAE log10 0.539 vs 1.079
- **killed: False** (rho < 0.5, or LOTO accuracy not above history)
- classes degenerate (>=95% in one class; accuracy test uninformative): False
