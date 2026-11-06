# Part A4: collapse point (one job, same node)

Job 60912397, 0.152 GPU node-h. Explore agent, 1-min warm-up, 5-min window, 3-min drain cap. Order: stock210 → both210 → both230 → stock230 (vLLM restarted between FCFS and priority configs). Rows for 110/190/250 are from Phase 2 (different jobs, 8-min window), for context.

| rate /min | stock throughput (÷ rate) | stock p95 s | stock prefix hit | both throughput (÷ rate) | both p95 s | both admission wait p95 s | source |
|---|---|---|---|---|---|---|---|
| 110 | 110 (1.00) | 19 | 86% | 110 (1.00) | 17 | 0 | Phase 2 |
| 190 | 188 (0.99) | 32 | 86% | 189 (0.99) | 29 | 0 | Phase 2 |
| 210 | 176 (0.84) | 107 | 81% | 189 (0.90) | 52 | 12 | A4 |
| 230 | 148 (0.65) | 248 (lower bound, 128 unfinished) | 70% | 200 (0.87) | 69 | 34 | A4 |
| 250 | 105 (0.42) | 786 (lower bound) | 48% | 199 (0.80) | 144 | 113 | Phase 2 |

**Reading.**
- **Stock's throughput falls below the arrival rate between 190 and 210 per min.** It keeps up at 190 (188/min, Phase 2) and is already behind at 210 (176/min, 84%, p95 107 s). At 230 it has collapsed (148/min, prefix hit 70%, 128 unfinished).
- **Collapse point ≈ 200 tasks/min.** Predicted ~220: the real cliff is a little earlier.
- **"Both" plateaus at ~190–200 completed per min,** the GPU's real ceiling, and turns the excess into gateway queue wait (p95 12 s at 210, 34 s at 230). Its p95 stays 52–69 s, with prefix hit 86%.

*Caveat: the 190-per-min point is from a different job (Phase 2). Within A4 only the upper side (210) is same-job.*
