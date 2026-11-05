# Test 1 (D5): resume-overhead breakdown

Run `/pscratch/sd/a/ap2568/dbkv/runs/d5/60839032`. Rule (PLAN §2b): mean over the 4 loaded points of p95(engine_overhead) / p95(turn e2e) >= 10% means pursue stateful sessions; < 10% means drop.

client_min (median `rest` of a 1-token request on an idle server) = 2.20 ms. Tokenizer time for re-sending the prompt as text: 4k 6.6 ms, 8k 13.0 ms, 20k 59.4 ms.

## Idle single requests (medians, ms)

| kind | ctx | client TTFT | queue | engine TTFT (prefill) | rest |
|---|---|---|---|---|---|
| one_token | 1 | 16.7 | 0.01 | 14.5 | 2.2 |
| fresh | 3796 | 276.1 | 0.01 | 269.7 | 6.4 |
| fresh | 7892 | 618.6 | 0.01 | 608.1 | 10.5 |
| fresh | 20180 | 1976.1 | 0.01 | 1952.4 | 23.7 |
| resume | 4112 | 38.9 | 0.01 | 32.6 | 6.3 |
| resume | 8208 | 48.5 | 0.01 | 38.4 | 10.1 |
| resume | 20496 | 79.4 | 0.01 | 56.2 | 23.2 |

## Loaded points: resumed turns (turn > 0, after warm-up)

| point | resumes | TTFT p50 / p95 | queue p50 / p95 | prefill p50 / p95 | rest p50 / p95 | engine_overhead p50 / p95 | turn e2e p95 | ratio |
|---|---|---|---|---|---|---|---|---|
| 20k × 4 | 87 | 121 / 1170 | 0 / 324 | 87 / 434 | 33 / 84 | 88 / 139 | 5947 | 2.3% |
| 20k × 8 | 71 | 2126 / 8664 | 1066 / 6152 | 801 / 2738 | 46 / 265 | 103 / 321 | 22222 | 1.4% |
| 8k × 12 | 251 | 98 / 680 | 0 / 169 | 75 / 341 | 23 / 149 | 34 / 160 | 5746 | 2.8% |
| 8k × 20 | 155 | 2816 / 5454 | 1778 / 4364 | 889 / 1185 | 77 / 190 | 90 / 200 | 19658 | 1.0% |

**Mean ratio over 4 points: 1.9% → DROP stateful sessions** (rule: ≥ 10% pursue).

