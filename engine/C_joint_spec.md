# Option C: joint speculation and prefill budget (design note)

*PLAN §2j, Phase 2 option C. Written Nov 16 2026 against the installed vLLM 0.33.0 (`$DBKV_ENV/lib/python3.11/site-packages/vllm`), before any GPU data. Code: `harness/vllm_jointspec/` (package `dbkv_jointspec`). This note is design, not a pre-registration; the C sub-entry in PLAN §2j holds the arms and the prediction.*

**Pre-registered prediction (PLAN §2j table, not a gate):** C gives ≥ 15% higher throughput at the ceiling than the best static vLLM speculation setting, with the same p50. It is measured on top of A, so the baseline is suffix decoding with a static `num_speculative_tokens`.

## 1. Where vLLM 0.33 decides the split

Line numbers are for `vllm/v1/core/sched/scheduler.py` unless another file is named.

| What | Where | Notes |
|---|---|---|
| Step token budget | `__init__` L139–143: `max_num_scheduled_tokens` (= `max_num_batched_tokens` unless set); `schedule()` L719 `token_budget = self.max_num_scheduled_tokens`, L722 `input_budget = max_num_batched_tokens`, L721 `draft_slots` (0 for suffix and n-gram) | `config/vllm.py` L2341 `_set_max_num_scheduled_tokens` sets it when a speculative config exists and warns below 8192. The Test S log (8B) showed 2048. **Check the value on 32B/TP4 in the server log.** |
| Spec token count per step | `__init__` L297 `self.num_spec_tokens` (= `num_speculative_tokens`; suffix sets it to the tree depth, 24 by default, `config/speculative.py` L1735) | The maximum per request. Suffix drafts are variable length up to this |
| Dynamic SD | `__init__` L322–329 `dynamic_sd_lookup` from `num_speculative_tokens_per_batch_size`; `schedule()` L1709–1714 picks one global K for the **next** step from the batch size | One K for all requests, by batch size only. With suffix it probably cannot be used: `v1/spec_decode/suffix_decoding.py` L43 asserts `num_speculative_tokens == self.num_speculative_tokens` (not tried) |
| Running requests (decode + in-flight prefill chunks) | `schedule()` L793–1036, in `self.running` order (FCFS) | `num_new_tokens = num_tokens_with_spec + placeholders − num_computed_tokens` (L839–848), so a decode request asks for 1 + len(`spec_token_ids`). Capped by `long_prefill_token_threshold` (L754–769, L844) and by what is left of `token_budget` |
| Which drafts are verified | L1009–1025: `spec_token_ids[:num_scheduled_spec_tokens]` go into `scheduled_spec_decode_tokens` | **When the budget runs out, the stock scheduler gives the next request only a slice of its drafts and the requests after it nothing at all this step** (the loop condition is `token_budget > 0`) |
| Waiting requests (new turns = new prefills) | L1049 onward, after all running requests, with what is left of `token_budget` | Prefix-cache hit found here (`_get_local_prefix_cache_hit` L664); chunked by `request_token_budget` (L1295) |
| Where drafts come from (sync) | `v1/engine/core.py` L700–706 `post_step` → `Scheduler.update_draft_token_ids` (L2862) sets `request.spec_token_ids` after each step, **before** the next `schedule()` | Async scheduling uses placeholders instead (`async_scheduler.py`); suffix disables async scheduling in 0.33 (PLAN §2h) |
| Acceptance | `update_from_output` L2346–2385: `num_accepted = len(sampled) − num_sampled_tokens_per_step`; rejected drafts roll back `num_computed_tokens` | Global: `SpecDecodingStats` (`make_spec_decoding_stats` L3305, per-position counts, exported to Prometheus). Per request: `request.spec_decode_metrics` (`RequestSpecDecodeMetrics`, L2381, L2950) only when `per_request_spec_decode_metrics` is on, and only reported at request end |
| Scheduler class choice | `v1/engine/core.py` L167 `vllm_config.scheduler_config.get_scheduler_cls()`; `config/scheduler.py` L231 | General plugins are loaded at L135 of the same `__init__`, before L167 |

**Two stock behaviours matter for C:**
1. *No decode floor.* With 24-token drafts, 64 decoding requests ask for 1,600 tokens. With a 1,024 budget the stock scheduler serves the first 41 requests fully (983 draft tokens) and the other 23 get **no token** this step (CPU test below). The skipped requests also leave the suffix proposer's batch, and `suffix_decoding.py` L92–95 stops their suffix-cache entry, so the next step rebuilds their prompt tree.
2. *Drafts before new prefills.* Running decodes (with all their drafts) come before waiting requests, so under load new turns' prefills (tool output, the re-rendered previous reply) get only what drafts leave. Drafts are also verified whatever their expected value: 40% of drafted tokens were rejected in Test S (acceptance 0.58–0.63).

## 2. Tracking acceptance per request

- **Signal:** `update_from_output` gives, per request per step, n drafted (minus grammar-invalid drafts) and m accepted. Accepted tokens are a prefix, so one step is m successes plus, if m < n, one failure of a per-position acceptance process. The MLE of the per-position conditional acceptance is p = m / (m + [m < n]).
- **Estimator (`AcceptanceTracker`):** EWMA counts (decay `EWMA`, default 0.9) per request and globally. Per-request p = (acc + w·p_global) / (trials + w), with w = `PRIOR` (default 4).
  - Agent turns are short (p50 21 output tokens per turn in Phase 1), so most requests have few verification steps. Early on, the global estimate dominates.
- **Hook:** the wrapper's `update_from_output` reads `scheduled_spec_decode_tokens`, `num_invalid_spec_tokens` and `sampled_token_ids` **before** the stock method (which mutates request state), then calls it unchanged.
- **Not used:** `SpecDecodingStats` is global and aggregated per logging interval; `RequestSpecDecodeMetrics` is per request but read only at finish. Suffix's own per-draft score (`draft.score` in arctic-inference) never leaves the worker. Using it would need a worker change (see §6).

## 3. The policy

Per step, before the stock `schedule()`:

1. **Budget** B = min(`max_num_scheduled_tokens`, `DBKV_JOINTSPEC_BUDGET`). Budget 0 means use vLLM's own.
2. **Demand:**
   - running requests with ≤ 1 uncomputed token are decodes (n_decode). Each has its drafts n_i and p_i;
   - running requests with more are in-flight prefill chunks (their remaining tokens);
   - waiting requests add (prompt − computed) × (1 − `WAIT_HIT`), only while there are free seq slots, and the scan stops once demand ≥ B. WAIT_HIT is an estimate, default 0.9; Phase 1 prefix hit was 93–95%.
3. **Decode first:** every decode request gets its 1 verified token; R = B − n_decode is left.
4. **Value model:** the k-th draft token of request i is worth p_i^k expected tokens, since it counts only if drafts 1..k−1 are accepted. One prefill token is worth θ (`THETA`, the split knob).
5. **Allocation** (`policy.allocate`, a pure function):
   - (a) draft positions with p_i^k ≥ max(θ, `MIN_VALUE`), best first, up to R;
   - (b) prefill gets min(demand, rest);
   - (c) if `FILL_LEFTOVER`, drafts with value in [`MIN_VALUE`, θ) take what is left;
   - drafts below `MIN_VALUE` are never verified.
   - Greedy on p^k is optimal for this separable concave objective, and each request's chosen drafts are always a prefix.
   - Drafts end up shared ∝ acceptance: a request gets ⌊log θ / log p_i⌋ "high" drafts.
6. **Apply:**
   - truncate each request's `spec_token_ids` to its allocation (the same slicing the stock code does at L1019);
   - if `DECODE_FIRST`, stably move decode requests ahead of running prefill chunks in `self.running`;
   - set `max_num_scheduled_tokens = B` for this one call;
   - run the stock `schedule()`;
   - restore.

**Knob meaning:**
- θ = 0: drafts first. This is close to static, but with the decode floor and acceptance-ordered trimming when B binds.
- θ = 0.5: a draft beats a prefill token while its chance of acceptance is ≥ 50%.
- θ > 1: prefill first; drafts only fill leftover budget.
- `BUDGET` sets how much compute there is to share. Below vLLM's cap it makes the step smaller, so each step is faster, and the policy picks what goes in.

**Cost:** `allocate` takes 0.2 ms per step at 128 requests × 24 drafts (pure Python). The demand scan is O(running + scanned waiting).

## 4. What changes vs the static setting

| | Static suffix (`num_speculative_tokens` = K) | C |
|---|---|---|
| Drafts per request | all suffix drafts up to K, whatever their acceptance | ∝ estimated acceptance; low-value tail dropped when compute is contended (or always, with `MIN_VALUE`) |
| Budget exhaustion | first-come requests get full drafts; later decodes get 0 tokens this step | every decode gets its token first; drafts trimmed across all requests |
| Prefill vs drafts | prefill (new turns, tool output, re-render) gets what running decodes leave | explicit exchange rate θ; prefill can displace low-value drafts |
| Step size | up to `max_num_batched_tokens` | optional smaller per-step budget (`BUDGET`) |
| Light load (budget not binding, θ ≤ value of all drafts) | — | identical batches (CPU test `test_theta_zero_matches_stock_when_uncontended`) |
| Outputs | verification is exact | same: dropping drafts never changes which token is accepted at temperature 0, only how many steps it takes. Batch shapes change, so near-tie flips (§2h S4h) can happen as with any batching change |

**Where the gain must come from, by Phase 1's numbers.** At the ceiling (60–80 running, ~100 ms steps, ~800 output tok/s and 2.5–3k prompt tok/s on 32B BF16 without speculation), a step carries ~80 decode + ~300 prefill tokens. With suffix at ~0.6 acceptance and ~4 accepted per draft, add roughly 6–7 drafts per request, ~500 tokens. That is ~900 tokens per step, below a 2,048–8,192 cap.
- So **the vLLM budget may not bind at the ceiling**, and with `BUDGET = 0` C would mostly be a no-op there.
- The lever is then `BUDGET` (≈ 512–1,024) plus `MIN_VALUE`. At ~900 tokens per step a 32B TP4 step is compute-bound, so the ~40% of rejected draft tokens (~200 per step) cost real time.
- Whether the freed time turns into throughput (prefill admitted sooner, shorter steps) rather than a longer p50 (fewer accepted tokens per step for each agent) is the empirical question C tests.

## 5. Implementation (switchable, not a fork)

- **Package:** `harness/vllm_jointspec/` (package `dbkv_jointspec`), a vLLM general plugin. Entry point `vllm.general_plugins: dbkv_jointspec = dbkv_jointspec:register`.
  - `register()` is a no-op unless `DBKV_JOINTSPEC=1`.
  - When on, it wraps `SchedulerConfig.get_scheduler_cls` so that the class vLLM picks (`Scheduler`, or `AsyncScheduler`) comes back as a subclass `JointSpec<cls>` = `(JointSpecMixin, cls)`. It is idempotent: vLLM loads general plugins in every process.
- **Alternative without the plugin:** `--scheduler-cls dbkv_jointspec.scheduler.JointSpecScheduler` (resolved lazily; active whenever named, knobs from env).
- **The mixin overrides only `__init__`, `schedule` and `update_from_output`,** and each calls `super()` unchanged.
  - It is a pass-through when no speculative method is configured or when async scheduling is on (with a warning).
  - No installed vLLM file is modified.
- **Optional decision log:** `DBKV_JOINTSPEC_LOG=path` (`{pid}` expands), one JSON line per `LOG_EVERY` steps, with budget, n_decode, drafts available / allocated (hi / lo), prefill demand / allocated, p_global, and the scheduled total and drafts as vLLM actually scheduled them.
- **Tests** (`harness/vllm_jointspec/tests`, stdlib unittest; on a CPU node, `VLLM_TARGET_DEVICE=cpu`):
  - `test_policy.py`: 13 pure tests (budget never exceeded, decode floor, θ extremes, leftover, min value, greedy optimality, tracker convergence and shrinkage, env parsing, speed);
  - `test_scheduler.py`: 4 tests on a real vLLM 0.33 `Scheduler`, built as in vLLM's own `tests/v1/core/utils.py` (Qwen3-8B config, n-gram speculative config with K = 24, fake KV config, injected drafts):
    - no-op without the env var;
    - stock vs joint split at budget 512;
    - decode floor at 64 × 25 > 1,024;
    - identical to stock when uncontended.

## 6. Risks (check these first on a GPU)

1. **The budget does not bind at the ceiling** (§4 arithmetic). Then C = stock unless `BUDGET` / `MIN_VALUE` are set. **First GPU check:** in the decision log at R\* with `BUDGET = 0`, is `spec_alloc < drafts_avail` in a meaningful share of steps? Also read `max_num_scheduled_tokens` from the server log.
2. **Trimming drafts raises p50.** Each agent gets fewer accepted tokens per step. The prediction asks for the same p50, and θ trades p50 against throughput, so θ and `BUDGET` must be fixed before the measured runs (a small calibration sweep, pre-registered).
3. **The acceptance estimate is weak per request.** Turns are short and every agent turn is a new vLLM request, so the per-request EWMA starts from the global prior each turn.
   - Acceptance in Test S was flat across settings (0.58–0.63), so the "∝ acceptance" part may differ little from uniform trimming.
   - Extension: key the estimate by agent task (the gateway can put the task id in the request id) or by turn type.
4. **The geometric model is wrong for suffix.** Suffix drafts are tree paths with per-token probabilities (`min_token_prob` 0.1), so acceptance probably falls faster along the draft than p^k. `MIN_VALUE` partly covers this. Exporting suffix's draft score to the scheduler would need a worker change.
5. **The prefill demand estimate is wrong.** WAIT_HIT is a constant, so it is wrong on cold turns and after evictions. Also, a waiting request may be blocked by KV or seq limits, so budget reserved for prefill goes unused. At worst that is a lost draft opportunity in that step, not a correctness problem.
6. **Interaction with stock mechanisms.**
   - `long_prefill_token_threshold` is unchanged.
   - `DECODE_FIRST` changes the preemption victim: `running[-1]` becomes a prefill chunk rather than the newest decode. Preemptions were 0 in Phase 1 below 100/min.
   - Priority scheduling (A(a) uses `--scheduling-policy priority`) preempts by priority, not position, so reordering does not change its victim. But A(a)'s gateway priorities and C's decode-first order interact; check that A(a) + C keeps task-start priority.
7. **Suffix-specific.**
   - Suffix forces the V1 runner, sync scheduling and (on 8B) a 2,048 cap, so C runs only in that mode. If a later vLLM makes suffix async, the mixin turns itself off (warning) and needs the placeholder path.
   - Variable-length drafts per request are already normal for suffix, so trimming adds no new batch shape. CUDA graph capture for mixed batches is unchanged, but check for unexpected graph-miss warnings.
8. **Steplog compatibility.** `dbkv_steplog` reads vLLM's iteration details, which now see smaller spec counts. That is intended, but its spec counters should be read as "verified", not "drafted".
9. **Overhead.** Pure Python, ~0.2–1 ms per step against ~100 ms steps, and sync scheduling has no overlap. Check it with a same-job burst, C on with θ = 0, `BUDGET = 0`, against C off.

## 7. Measurement plan sketch (for the PLAN sub-entry; Aryan decides)

- **Baseline arms:** A-system + suffix with static K ∈ {4, 8, 16, 24}, the best one by throughput at R\*.
- **C arms:** A-system + suffix K = 24 + `DBKV_JOINTSPEC=1` at a pre-registered (θ, BUDGET, MIN_VALUE) chosen from a short calibration (burst + one open-loop cell).
- **Load and repeats:** at R\* and R_o, 3 repeats, same-job controls.
- **Also report:** decision-log shares (hi / lo / trimmed drafts, prefill share), acceptance, and p50 and p95.
