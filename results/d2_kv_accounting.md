# KV accounting: why full uses 69% KV vs explore 27% at c = 64 (step-6 logs, caching on)

Source: step-6 caching-on job 60876091 (300 questions, frozen agent). No new logging was needed.
- KV used = mean `vllm:kv_cache_usage_perc` × the 139,232-token pool. That counts blocks held by running requests; cached but unreferenced blocks are free.
- R = mean running requests (vLLM gauge).
- ctx = context of a running request (prompt + half its output), weighted by server-side prefill + decode time.
- Shared prefix per request = that task's first-turn prompt − ~60 question tokens: instructions + tool specs, plus the per-DB brief for full. Its median per database is the per-DB prefix.

| arm | c | R | KV used (tokens, %) | ctx/request | shared prefix/request | unique/request | R × unique | prefixes stored once | model total | no-sharing R × ctx | first-turn prefix misses (extra beyond 1/DB) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| explore | 8 | 5.5 | 8,974 (6%) | 1,998 | 462 | 1,536 | 8,435 | 462 | 8,897 (-1%) | 10,972 | 2 (0) |
| explore | 32 | 15.4 | 25,204 (18%) | 2,071 | 462 | 1,609 | 24,803 | 462 | 25,265 (+0%) | 31,924 | 2 (0) |
| explore | 64 | 25.2 | 37,054 (27%) | 1,923 | 462 | 1,461 | 36,888 | 462 | 37,350 (+1%) | 48,551 | 2 (0) |
| full | 8 | 6.3 | 28,465 (20%) | 6,485 | 4,935 | 1,550 | 9,822 | 47,539 | 57,361 (+102%) | 41,099 | 12 (1) |
| full | 32 | 23.1 | 65,486 (47%) | 6,495 | 5,024 | 1,471 | 33,987 | 47,539 | 81,526 (+24%) | 150,059 | 12 (1) |
| full | 64 | 43.2 | 96,196 (69%) | 6,313 | 4,909 | 1,404 | 60,604 | 47,539 | 108,143 (+12%) | 272,529 | 13 (2) |

## Answer (c = 64)
- **Per-agent tokens are not the difference.** A full request's unique context is 1,404 tokens; an explore request's is 1,461. Briefed agents carry about the same private conversation.
- **Prefix sharing works.** Without it, full would need R × ctx = 272,529 tokens, about 2× the pool. Measured use is 96,196.
- **The gap (59,143 tokens) has two parts:**
  1. **More requests in flight.** R = 43.2 vs 25.2, because full requests are longer (bigger prefill) and agents spend more of their time inside a request. That's ≈ (43.2 − 25.2) × 1,461 ≈ 26,193 tokens.
  2. **The per-database briefs themselves,** each held once: 11 DBs × ~4,322 ≈ 47,539 tokens when all are in flight.
  - Together the model gives 108,143 vs 96,196 measured (+12%).
  - At c = 8 the model over-counts the stored-once term, because fewer databases are in flight at once (+102%). The explore model is within 1%.
- **Simultaneous same-database first requests barely duplicate the prefix.** 13 of 300 full tasks missed the brief on turn 1 at c = 64, against 11 databases, so ≤ 2 extra prefills. That's < 3% of KV even if they overlapped, so it's negligible.
  - *Pre-registered prediction (§2f): "most of it is per-agent tokens; duplicates < 10%".* **The first half is wrong** (the gap is concurrency + briefs stored once; per-agent tokens are equal). **The second half is right.**
- **Implication:** a shared brief costs memory once per database plus the longer requests it causes. A smaller whole-DB brief (compact, ~920 tokens/DB) should cut both terms. Phase 1 measures it.
