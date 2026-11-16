# Option E: task-aware KV eviction and preemption (design note)

*PLAN §2j, Phase 2 step E (order A → C → B → E → D). Pre-registered prediction there, not a gate: **≥ 10% fewer
prefill tokens at overload**, measured on top of the best system after A, C and B. This note is the design;
it holds no measurement. Code: `harness/vllm_taskevict/` (engine plugin) and `harness/gateway/gateway.py
--taskevict` (gateway side). Written against the installed vLLM **0.33.0** (`g4ba787ec9`); line numbers below
are from that install.*

## 1. What E is for

An agent task is a chain of requests. Between two turns (tool call, DuckDB query) the task is **paused**:
its KV blocks are no longer referenced by any request (ref count 0) and survive only as prefix-cache entries
in the free list. Stock vLLM V1 evicts those entries **LRU over all free blocks**, without knowing which task
they belong to or whether that task is finished. So under KV pressure it can evict a paused task that will
come back in seconds, while keeping the blocks of tasks that already returned their answer and will never be
read again.

E gives the block manager the one bit of task knowledge it is missing:
- **(i)** blocks whose owner tasks have all **ended** are evicted first;
- **(ii)** blocks of **paused live** tasks are evicted last (LRU among them), with a TTL as a safety net;
- **(iii)** when the scheduler must **preempt**, the victim is the request of the lowest-priority task (the
  youngest task start).

**Where it can help (Phase 1, `results/p1_baseline.md`).** True eviction of a live task's conversation
("evicted proper") is ~0 up to 60/min. It reaches 12% / 32% / 35% of uncached prompt tokens at
100 / 140 / 180 per min on stock vLLM, with KV at 85–100%. That share is E's ceiling: E cannot remove
"new" tokens (tool output), cold first turns, or the **re-render** of the previous reply (22–29% of uncached
prefill at normal load: the chat template re-renders the history, so the cache hit for turn n always stops
at P_{n−1}; that is a prompt-side problem, not an eviction one). Whole-task admission (A(a)) already lowers
KV pressure, so on top of A–C, E matters only at loads where KV is still full. See risk R1.

## 2. Where vLLM 0.33 V1 decides

### 2.1 Eviction order: one linked list

| Piece | File:line | What it does |
|---|---|---|
| `KVCacheBlock` | `v1/core/kv_cache_utils.py:161` | `@dataclass(slots=True)`: `block_id, ref_cnt, _block_hash, prev_free_block, next_free_block, pool, is_null`. No room for extra attributes (slots), so task metadata must live outside the block. |
| `FreeKVCacheBlockQueue` | `kv_cache_utils.py:258–519` | Doubly linked list over the blocks' own prev/next pointers, with fake head/tail. `popleft(_n)`, `remove` (O(1) from the middle), `append(_n)`, `prepend_n`, `get_all_free_blocks`, `iter_blocks_after`. |
| `BlockPool.__init__` | `v1/core/block_pool.py:159–200` | `self.free_block_queue = FreeKVCacheBlockQueue(self.blocks)` (l.182), then pops block 0 as the null block. |
| `BlockPool.get_new_blocks` | `block_pool.py:706–740` | `free_block_queue.popleft_n(n)` then `_maybe_evict_cached_block` on each: **the front of the list is the eviction order**. |
| `BlockPool.touch` | `block_pool.py:792–810` | Prefix hit on a free cached block: `free_block_queue.remove(block)`, `ref_cnt += 1`. |
| `BlockPool.free_blocks` | `block_pool.py:816–849` | `ref_cnt -= 1`; at 0, hash-less blocks are **prepended** (reused first, LIFO), cached blocks **appended** (LRU). Callers pass blocks in reverse order, so a chain's tail is evicted before its head. |
| `SingleTypeKVCacheManager.free` | `v1/core/single_type_kv_cache_manager.py:591–599` | `block_pool.free_blocks(reversed(self.pop_blocks_for_free(request_id)))`. |
| `KVCacheManager.free` / `pop_blocks_for_free` | `v1/core/kv_cache_manager.py:629, 660` | The two entry points with the **Request** in hand. `pop_blocks_for_free` is the deferred path (async scheduling: blocks go back to the pool one step later, `scheduler.py:3084–3093`). |
| `BlockPool.unpin_blocks` | `block_pool.py:748–767` | Offload path: `append_n` regardless of hash. Not used in our runs. |
| `BlockPool.reset_prefix_cache` | `block_pool.py:871–910` | Clears all hashes (used between our experiment cells). |

The only other reader of `free_block_queue` in vLLM is `v1/simple_kv_offload/manager.py:636`
(`iter_blocks_after`), not used by us.

So **eviction order = the order of one list**, and every change to it goes through five queue methods. That
is the hook: replace the pool's queue object with one that keeps several lists and pops them in tier order.

### 2.2 Preemption victim

`Scheduler.schedule()` (`v1/core/sched/scheduler.py:911–980`), when `allocate_slots` returns `None` for a
running request:

```python
if self.policy == SchedulingPolicy.PRIORITY:
    preempted_req = max(self.running, key=lambda r: (r.priority, r.arrival_time))
else:
    preempted_req = self.running[-1]
```

then `_preempt_request` (l.1799) frees its blocks through `_free_request_blocks` → `KVCacheManager.free`
and puts it at the front of the waiting queue.

Our gateway's `--priority` already sets `priority = task_start_ms − gateway_t0_ms` (smaller = older = more
important), and the best system after A(a) runs `--scheduling-policy priority`. So **policy (iii) is already
stock behaviour** in that configuration: the victim is the running request with the largest priority value,
i.e. the youngest task. Under FCFS the victim would be `running[-1]` (the most recently scheduled request),
which is not task-aware; the decision is inlined in `schedule()`, so changing it would mean re-implementing
that method. E therefore **does not patch preemption**; it requires the priority policy and warns at
startup if the policy is not `priority`. What E adds is that the victim's freed blocks are filed as *paused*
(its task is live and will be re-admitted), so its recompute after re-admission can hit the cache.

## 3. Getting task identity and task end into the engine

### 3.1 Task id on every request: `vllm_xargs` → `SamplingParams.extra_args`

The OpenAI chat request in 0.33 has `vllm_xargs: dict[str, str|int|float|list]`
(`entrypoints/openai/chat_completion/protocol.py:533`), copied into `SamplingParams.extra_args` (l.783).
`SamplingParams` is serialized to the engine core with the request, and the scheduler's `Request` keeps
`request.sampling_params` (`v1/request.py:87`). So no header plumbing and no API-server change are needed.

The gateway (`--taskevict http|inband`) adds to every body
`"vllm_xargs": {"dbkv_task": "<task_id>@<task_start>", "dbkv_task_start": <epoch s>}`, merged with any
`vllm_xargs` the client sent. The id carries the start time because the W3 load generator restarts task ids
at `t00000` in every cell.

### 3.2 Task end: two channels

The gateway learns the end from `POST /gw/task_end` (the load generator sends it when a task returns its
final SQL, and also for tasks cancelled at the drain cap). The engine core is a separate process from the
API server, so the signal needs a path into the scheduler:

- **`http` (default):** the plugin starts a tiny HTTP listener **inside the engine-core process** when the
  `Scheduler` is constructed (`DBKV_TASKEVICT_HOST:PORT`, default `127.0.0.1:8899`, `POST /task_end
  {"task_id"}` or `{"task_ids": [...]}`, `GET /stats`). The handler thread only puts the id on a thread-safe
  queue; the scheduler thread drains it at the start of the next `schedule()`. The gateway sends it in the
  background after answering task_end, so the agent never waits on it.
- **`inband`:** the gateway sends a 1-token `/v1/completions` request with `vllm_xargs {"dbkv_task_end": id}`
  to the task's backend; the plugin's `Scheduler.add_request` wrapper sees the marker and queues the end. No
  port, but it costs one tiny request per task (priority 0, so it is scheduled at once). Fallback for when a
  port cannot be used.

An extra field on the task's *last* request does not work: the gateway does not know a request is the last
one until the agent has read its answer.

## 4. The policy

### 4.1 Tiers

The pool's queue becomes `TaskTieredFreeQueue` (`harness/vllm_taskevict/dbkv_taskevict/tiers.py`): four
vLLM `FreeKVCacheBlockQueue` instances, popped in this order:

| Tier | Contents | Order inside |
|---|---|---|
| FIRST | hash-less blocks (vLLM's own prepend path) and the never-used initial blocks | vLLM's |
| ENDED | cached blocks whose every owner task has ended **(i)** | order of task end; tail blocks first |
| NORMAL | cached blocks with no task tag; blocks shared by ≥ 2 tasks that all left; blocks of TTL-expired tasks | LRU (vLLM's append order) |
| PAUSED | cached blocks held by at least one live task **(ii)** | LRU (append order) |

All four count as free (`num_free_blocks` is the sum), exactly as cached blocks do in stock vLLM, so
`get_usage()`, admission checks and allocation see the same numbers. Nothing is pinned: when FIRST, ENDED
and NORMAL are empty, PAUSED blocks are evicted LRU, as stock would. **With no task tags, ENDED and PAUSED
stay empty and FIRST ++ NORMAL is vLLM's list, block for block** (tested, §6).

### 4.2 Ownership

`KVCacheBlock` has `__slots__`, so metadata is per block id in the queue: `live_owners[bid]` (live tasks
that held the block), `flags[bid]` (TAGGED, SHARED, KEEP) and `task_blocks[task]` (ordered set of block ids,
for re-filing at task end). The plugin wraps `KVCacheManager.free` and `pop_blocks_for_free`: before vLLM
frees a request, every block it holds (`coordinator.get_blocks(request_id)`) gets the request's task noted
as owner. That covers normal finish, abort, preemption and the deferred-free path. A block noted by a second
distinct task is SHARED (system prompt, schema brief).

When a block reaches ref count 0 and is appended, its tier is: PAUSED if any live owner; else NORMAL if
SHARED or KEEP; else ENDED if TAGGED; else NORMAL. When a block is popped (re-used, i.e. evicted) its
metadata is dropped. `touch` (prefix hit) removes it from its tier and keeps the metadata.

### 4.3 Task state (`registry.py`)

- **live:** from the first request seen (`Scheduler.add_request`) until end or expiry;
- **ended:** on task_end. Its free blocks without another live owner move PAUSED → ENDED (tail first).
  If a free arrives after the end (deferred free), the blocks go straight to ENDED;
- **expired (TTL safety):** no request in flight (counted by `add_request` / `_free_request`) for
  `DBKV_TASKEVICT_TTL` s (default 300). Its blocks move PAUSED → **NORMAL** (plain LRU, not "ended": the end
  signal may simply have been lost). A new request revives the task. 300 s is above the gateway's 120 s
  idle timeout and covers the W3 tail (an SF100 task with five 60 s timeouts spends ~300 s in DuckDB).
  A request that runs for minutes (runaway generation) keeps its task live because it is in flight;
- **reset:** a successful `reset_prefix_cache` (between cells) clears all task state and puts every free
  block in FIRST.

All of this runs on the engine-core busy-loop thread; only the listener runs elsewhere and touches nothing
but a `SimpleQueue`.

### 4.4 Ablation modes (`DBKV_TASKEVICT_MODE`)

`full` (i)+(ii); `ended_only` (no PAUSED tier); `paused_only` (no ENDED tier); `tag_only` (all hooks and
bookkeeping, no reordering: the overhead control, identical eviction order to stock).

## 5. Implementation (switchable, not a fork)

- `harness/vllm_taskevict/`: package `dbkv_taskevict`, entry point `vllm.general_plugins:
  dbkv_taskevict = dbkv_taskevict:register`. vLLM calls `load_general_plugins()` in every process, including
  the engine core (`v1/engine/core.py:135`). `register()` returns at once unless `DBKV_TASKEVICT=1`.
- Monkeypatches (`patch.py`), installed once per process: `BlockPool.__init__`,
  `BlockPool.reset_prefix_cache`, `KVCacheManager.free`, `KVCacheManager.pop_blocks_for_free`,
  `Scheduler.__init__`, `Scheduler.add_request`, `Scheduler._free_request`, `Scheduler.schedule`
  (`AsyncScheduler` inherits all four). No installed file changes. `install()` checks the vLLM version
  and that the queue / manager / scheduler methods it relies on exist.
- Gateway: `--taskevict off|http|inband` (default off: the gateway is byte-for-byte the old proxy),
  `--taskevict-endpoints` (one URL per backend). Events `ev="taskevict_end"` in the gateway log; counters
  `taskevict_sent` / `taskevict_errors` in `/gw/stats`.
- Install command and run flags: `harness/vllm_taskevict/README.md`.

## 6. CPU tests (no GPU)

`srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:20:00 harness/vllm_taskevict/tests/cpu_tests.sh`

- **Equivalence with vLLM's queue:** a real `BlockPool` with the stock queue and one with the tiered queue,
  driven by the same random sequence (alloc, hash, prefix-hit `touch` incl. shared blocks, free, `unpin`),
  3 seeds × 4000 operations, with no tags and in `tag_only` mode: identical blocks handed out and identical
  free-list order after every operation.
- **Policy:** ended → untagged → paused order (and stock LRU on the same sequence evicting the paused
  task); shared blocks protected while any owner lives and NORMAL once all owners left; free-after-end;
  re-free after a hit is not "shared"; hash-less blocks; reset; TTL expiry and revival; listener round trip.
- **Plugin on vLLM's real `KVCacheManager`:** a paused task (320 tokens), then 10 short tasks that end
  (half through the deferred-free path) churn a 63-block pool. Stock order: the paused task's next turn
  hits **0** tokens; with E: **320** (all), 0 paused evictions.
- **Plugin in vLLM's real V1 `Scheduler`** (Qwen3-8B config only, offline): tagging via `add_request`,
  in-band end drained by `schedule()`, `_free_request` bookkeeping; and a forced preemption under
  `policy="priority"` in a 15-block pool that picks the younger task (added first, so FCFS would have
  picked the other) and files its 7 blocks as PAUSED.
- **Gateway** against `mock_vllm.py`: off by default (no `vllm_xargs`), http and in-band end signals, the
  client's own `vllm_xargs` kept, a dead endpoint counted as an error without delaying task_end.
- **Cost:** a 320-block turn (alloc, hit, note owners, free) costs ~400 µs tiered vs ~134 µs stock in
  Python, i.e. ~0.3 ms per finished request; at ~6 requests/s that is ~0.15% of the engine thread.

## 7. Risks (check the first ones first on a GPU)

1. **R1, nothing to win at the chosen overload.** On stock, evicted proper is ~0 at R_o = 60/min, and
   admission (A(a)) lowers KV pressure further. If KV never fills on the A–C system at the measured
   overload, E saves ~0 prefill tokens whatever the policy. Check KV usage and `evicted` counts per tier
   (`DBKV_TASKEVICT_LOG`) in a short run at the overload level before the 3-repeat measurement; the
   loads where stock evicts are 100–180/min.
2. **R2, the end signal does not arrive or arrives for the wrong id.** Check `end_msgs`, `end_unseen`
   (ends for tasks the engine never saw: id mismatch), `late_requests` (requests for ended tasks), and the
   gateway's `taskevict_errors`. With `DBKV_TASKEVICT_PORT` the listener must bind in the engine core: look
   for "task_end listener on" in the vLLM log. Two vLLM servers on one node need different ports.
3. **R3, the policy hurts reuse across tasks.** ENDED-first drops a finished task's private blocks. If the
   schema brief / system prompt was used by only one task so far, it is ENDED too, and the next task on that
   DB pays a cold prefill (stock LRU might have kept it). Watch the **cold** (turn-1) share; if it rises,
   promote short prefixes to NORMAL (e.g. never file the first N blocks of a chain as ENDED).
4. **R4, overhead on the scheduler thread.** Measured ~0.3 ms per finished request on CPU; with async
   scheduling the scheduler overlaps the GPU, so expect nothing visible. Check with `tag_only` vs off on the
   burst (as P1-e did for the step log).
5. **R5, protecting paused tasks too long.** PAUSED is evicted last but not pinned, so it cannot deadlock.
   The TTL only moves an idle task to plain LRU. A wrong TTL changes little; `expirations` shows how often
   it fires.
6. **R6, preemption depends on configuration.** (iii) holds only with `--scheduling-policy priority` and
   the gateway's `--priority`. The plugin warns otherwise. Preemptions were 0 at 40–60/min in Phase 1,
   so (iii) may never act in the measured cells.
7. **R7, vLLM internals.** Monkeypatches on private methods (`_free_request`, `free_block_queue`) of
   0.33.0. A vLLM upgrade must re-run the CPU tests; `install()` refuses to patch if a method it relies on
   is missing.
8. **R8, interaction with other options.** Suffix decoding (A(b)) and C's scheduler change also touch the
   scheduler. The plugin wraps `schedule()` and `add_request` without changing their logic, so it composes
   with any scheduler subclass that calls them; a C implemented as a subclass overriding `schedule()` must
   still call `super().schedule()` (or call `REGISTRY.tick()` itself).
9. **R9, what E cannot do.** The re-render of the previous reply (22–29% of uncached prefill) and new
   tool-output tokens are untouched. The ≥ 10% prediction is on *all* prefill tokens, so E needs the
   evicted-proper share at the measured load to be well above 10% to meet it.

## 8. GPU check before the measurement (suggested, ~10 min inside an existing job)

Start vLLM with `DBKV_TASKEVICT=1 DBKV_TASKEVICT_LOG=...` and the gateway with `--priority --taskevict
http`; run a short open-loop cell at an overload where KV fills (e.g. 140/min). Look for: the listener
line in the vLLM log; `end_msgs` ≈ finished tasks and `end_unseen` = 0; nonzero `evicted.ended`;
`evicted.paused` well below stock's evictions of live tasks; no change in decode tok/s vs `tag_only`.
