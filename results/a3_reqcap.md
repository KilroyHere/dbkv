# Part A3: request-cap baseline vs "both" at 250 tasks/min (one job, same node)

Job 60912396, 0.134 GPU node-h. Explore agent; 1-min warm-up, 5-min window, 3-min drain cap (unfinished tasks counted as unfinished). Order: reqcap64 → both → reqcap32. vLLM restarted per config.

| setting | p50 s | p95 s | throughput /min | unfinished | accuracy | prefix hit | admission wait p95 s |
|---|---|---|---|---|---|---|---|
| stock vLLM, --max-num-seqs 64 | 158.8 | 306.2 | 130.4 | 364 | 33.7% | 64.7% | 0 |
| gateway: admission K=77 + priority | 52.3 | 100.9 | 196.8 | 1 | 45.0% | 86.0% | 67 |
| stock vLLM, --max-num-seqs 32 | 190.3 | 340.8 | 117.6 | 446 | 31.0% | 62.1% | 0 |

**Rule A3:** "both" p95 ≥ 15% lower than the best request cap (reqcap64) AND throughput ≥ 95% of its throughput.
- p95: 100.9 vs 306.2 s → **−67%**. The request-cap p95 is a lower bound: 364 tasks were unfinished at the drain cap.
- throughput: 196.8 vs 130.4 per min → **151%**.
- **A3: MET** (predicted MET; predicted p95 ~150 vs ~300 s, observed 101 vs 306 s).

**Why:** a request cap limits *running requests*, not *tasks*. Tasks keep arriving and interleave between turns, so their cached prefixes are evicted (prefix hit 62–65% vs 86%) and every resumed turn re-prefills. The cap only moves the queue inside vLLM. Task-level admission keeps the admitted tasks' caches warm and queues whole tasks at the gateway.

*Caveat: 1 rep. Unfinished request-cap tasks lower their accuracy (31–34% vs 45%) because they count as wrong.*
