# Phase 2: agent gateway on one GPU (explore agent, open-loop Poisson arrivals)

- **Jobs:** 60891199 (FCFS server: stock, admission) and 60891201 (priority server: priority, both). 0.69 GPU node-h. 1 rep per point.
- **Setup:** K = 77 (from `kv_limit.py` with the measured mean active-task context). Warm-up 120 s, measured 480 s, drain cap 600 s. Prefix cache reset between cells. Self-check S2 passed on retry (job 60890137).

| rate /min | policy | p50 s | p95 s | throughput /min | incomplete | accuracy | admission wait p50 / p95 s | prefix hit | GPU idle | gateway overhead p50 / p95 ms | sim p50 / p95 / thr |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 110 | stock | 5.64 | 18.75 | 109.8 | 0 | 44.1% | 0.0 / 0.0 | 86.0% | 0.0% | 0.08 / 0.11 | 5.9 / 17.2 / 111 |
| 110 | priority | 4.98 | 16.79 | 109.8 | 0 | 44.4% | 0.0 / 0.0 | 86.0% | 0.0% | 0.17 / 0.26 | 5.9 / 17.2 / 111 |
| 110 | admission | 4.78 | 14.61 | 109.6 | 0 | 44.0% | 0.0 / 0.0 | 85.8% | 0.0% | 0.08 / 0.10 | 5.9 / 17.2 / 111 |
| 110 | both | 5.29 | 17.34 | 109.6 | 0 | 44.5% | 0.0 / 0.0 | 85.9% | 0.0% | 0.17 / 0.26 | 5.9 / 17.2 / 111 |
| 190 | stock | 10.71 | 31.61 | 188.1 | 0 | 45.3% | 0.0 / 0.0 | 86.0% | 0.0% | 0.08 / 0.11 | 23 / 210 / 175 |
| 190 | priority | 10.50 | 31.38 | 189.5 | 0 | 45.1% | 0.0 / 0.0 | 85.9% | 0.0% | 0.17 / 0.27 | 22 / 91 / 181 |
| 190 | admission | 12.07 | 34.50 | 188.4 | 0 | 45.2% | 0.0 / 0.0 | 85.9% | 0.0% | 0.08 / 0.11 | 19.7 / 51 / 190 |
| 190 | both | 9.89 | 29.20 | 189.0 | 0 | 45.0% | 0.0 / 0.0 | 86.0% | 0.0% | 0.17 / 0.27 | 19.7 / 51 / 190 |
| 250 | stock | 352.07 | 786.34 | 104.8 | 237 | 41.6% | 0.0 / 0.0 | 48.5% | 0.0% | 0.07 / 0.12 | 726 / 1208 / 73 |
| 250 | priority | 250.83 | 430.06 | 134.2 | 0 | 44.7% | 0.0 / 0.0 | 63.4% | 0.0% | 0.18 / 0.31 | 420 / 691 / 111 |
| 250 | admission | 122.59 | 203.95 | 184.8 | 0 | 44.7% | 93.5 / 176.0 | 85.9% | 0.0% | 0.08 / 0.12 | 118 / 182 / 195 |
| 250 | both | 94.64 | 144.25 | 199.1 | 0 | 44.2% | 67.8 / 113.3 | 86.2% | 0.0% | 0.18 / 0.29 | 118 / 182 / 195 |

## Rule P2 (§2f): at the above-capacity rate (250/min), "both" p95 ≥ 20% lower than stock and throughput ≥ 95% of stock's

- p95: both 144.3 s vs stock 786.3 s → **−82%**. Stock's p95 is a lower bound: 237 of its tasks were still unfinished at the drain cap.
- throughput: 199.1 vs 104.8 per min → **190% of stock's**.
- **P2: MET.**

## Readings
- **Above capacity, stock collapses.** Prefix hit falls to 48.5%; waiting requests lose their cached prefixes and re-prefill, so throughput drops to 105/min against 250 arriving.
  - Priority alone keeps more of the cache (63%) and reaches 134/min, p95 −45%.
  - Admission keeps the cache warm (86%) and holds ~185–199/min. Its tasks wait at the gateway instead: queue wait p95 176 s (admission), 113 s (both).
  - **Both is best on every measure:** p95 144 s, 199/min.
- **At 190/min (the simulator's "capacity"), the real GPU did not collapse in any policy** (p95 29–34 s, ~188/min). The simulator underestimates real capacity, so 190 was below the real cliff and 250 above it. All four policies are within ±10% p95 at 190.
- **At 110/min the four p95s spread from 14.6 to 18.8 s.** No admission queueing happens there (K is never reached), so that 22% spread is run-to-run variation (cf. the S2/S3 drift). The §2f prediction "within ±5% below capacity" is not met as stated; it's noise, not policy.
- **GPU idle under admission: 0%** at every rate. Explore-agent pauses are ~15 ms, so admission never starves the GPU here. Long tool waits are a roadmap case.
- **Gateway overhead: 0.08 ms per request (p50) without priority, ~0.17 ms with priority injection;** p95 ≤ 0.31 ms.
- **Simulator vs real at 250/min:** admission p95 182 predicted vs 204 real; both 182 vs 144; priority 691 vs 430; stock ≥ 1,208 vs ≥ 786. Right ordering and right magnitude for the admission policies.
- **Accuracy is unchanged by policy** (44–45%), except stock at 250 (41.6%), where unfinished tasks count as wrong.

*Caveats:*
- *1 rep.*
- *Stock/admission and priority/both ran in different jobs on different nodes (node variation up to ~16%, from S2/S3), so cross-job comparisons are only good to that level. The P2 effect (−82% p95, +90% throughput) is far larger.*
- *Over-capacity p95 depends on window length, because queue wait grows with time.*
