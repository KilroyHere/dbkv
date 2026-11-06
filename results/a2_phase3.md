# Part A2: Phase 3, routing across 2 replicas

- **Jobs:** 60912394 (compact brief: round-robin / least-loaded / affinity + cap 1.25) and 60912395 (full-schema brief, extra arm added after the overnight run: round-robin / affinity). 2 × A100-40GB each; 0.68 + 0.48 GPU node-h.
- **Design:** stock FCFS servers, no admission. 1-min warm-up, 8-min measured window (as pre-registered), 3-min drain cap (unfinished counted as unfinished). The policy order alternates within each rate.

| brief | rate /min | policy | p50 s | p95 s | throughput /min | unfinished | accuracy | prefix hit |
|---|---|---|---|---|---|---|---|---|
| compact | 380 | round_robin | 27 | 236 | 304 | 178 | 48.8% | 85.6% |
| compact | 380 | least_loaded | 104 | 325 | 244 | 472 | 45.5% | 78.2% |
| compact | 380 | affinity | 74 | 304 | 259 | 371 | 46.7% | 78.6% |
| compact | 500 | affinity | 201 | 451 | 244 | 1409 | 35.4% | 74.5% |
| compact | 500 | least_loaded | 236 | 463 | 212 | 1716 | 32.4% | 71.9% |
| compact | 500 | round_robin | 236 | 464 | 211 | 1704 | 32.6% | 72.0% |
| full | 380 | round_robin | 260 | 503 | 149 | 1488 | 29.4% | 88.3% |
| full | 380 | affinity | 235 | 491 | 163 | 1302 | 32.3% | 89.5% |
| full | 500 | affinity | 294 | 545 | 162 | 2400 | 23.4% | 90.3% |
| full | 500 | round_robin | 316 | 550 | 149 | 2614 | 20.6% | 89.2% |

## Rule P3 (§2f): affinity + cap p95 ≥ 15% lower than round-robin at the above-capacity rate (500/min)

- compact, 380/min: p95 304 vs 236 s → **+29.0%**; throughput 259 vs 304 per min (-15%); prefix hit 78.6% vs 85.6%
- compact, 500/min: p95 451 vs 464 s → **-3.0%**; throughput 244 vs 211 per min (+15%); prefix hit 74.5% vs 72.0%
- full, 380/min: p95 491 vs 503 s → **-2.4%**; throughput 163 vs 149 per min (+10%); prefix hit 89.5% vs 88.3%
- full, 500/min: p95 545 vs 550 s → **-1.0%**; throughput 162 vs 149 per min (+9%); prefix hit 90.3% vs 89.2%

**P3: NOT MET with compact (−3.0% at 500/min) and NOT MET with the full schema (−1.0%).** Under B1 ("neither"), routing is dropped and reported as a negative result.

## Readings
- **Both rates were above 2-GPU capacity for both briefs,** because routing alone has no admission control.
  - Compact completes 211–304/min against 380–500 offered; full only 149–163/min.
  - p95 is therefore dominated by queueing and the drain cap (hundreds to thousands of unfinished tasks). That leaves little room for a cache-locality effect to show in p95.
- **Affinity's real but small effect is on throughput at 500/min:** +15% for compact, +9% for full. Prefix hit is +2.5 / +1.1 points.
- **At 380/min with compact, round-robin was best** (p95 236 vs 304 s; 304 vs 259 per min). Least-loaded was worst. RR ran first in that rate's order, so drift may favour it somewhat.
- **Predictions:**
  - compact affinity vs RR, −5% / −10% predicted vs +29% / −3% observed;
  - full, −15% / −30% predicted vs −2.4% / −1.0% observed: **the KV-accounting-based full-arm prediction was wrong** (freed brief memory is swamped by overload);
  - prefix-hit gains were smaller than predicted.

*Caveat: 1 rep. Accuracy at these rates is dragged down by unfinished tasks (counted as wrong).*
