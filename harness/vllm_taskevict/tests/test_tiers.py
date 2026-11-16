"""CPU tests of dbkv_taskevict against vLLM 0.33's real BlockPool / FreeKVCacheBlockQueue / KVCacheManager.

    srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:20:00 bash -c \
      'source setup/env.sh && python harness/vllm_taskevict/tests/run_tests.py'

No GPU, no model; the package need not be installed (the test puts harness/vllm_taskevict on sys.path).
Plain test functions (pytest-compatible; the env has no pytest, so run_tests.py runs them).
"""
import json, os, random, sys, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vllm.v1.core.block_pool import BlockPool  # noqa: E402
from vllm.v1.core.kv_cache_utils import (BlockHash, FreeKVCacheBlockQueue,  # noqa: E402
                                         make_block_hash_with_group_id)

from dbkv_taskevict.registry import TaskRegistry  # noqa: E402
from dbkv_taskevict.tiers import ENDED, FIRST, NORMAL, PAUSED, TaskTieredFreeQueue  # noqa: E402


# ---------------------------------------------------------------- helpers
class Live:
    """is_live() for direct queue tests."""

    def __init__(self):
        self.dead = set()

    def __call__(self, t):
        return t not in self.dead


def tiered_pool(n, live=None, **kw):
    """A real BlockPool whose queue is swapped exactly as the plugin's BlockPool.__init__ wrapper does."""
    p = BlockPool(num_gpu_blocks=n, enable_caching=True, hash_block_size=16)
    q = TaskTieredFreeQueue(p.free_block_queue, p.blocks, live or Live(), **kw)
    p.free_block_queue = q
    return p, q


_h = [0]


def give_hash(pool, block):
    _h[0] += 1
    key = make_block_hash_with_group_id(BlockHash(_h[0].to_bytes(32, "big")), 0)
    pool._insert_block_hash(key, block, None)


def ids(blocks):
    return [b.block_id for b in blocks]


def run_request(pool, q, n, task=None, cache=True):
    """Allocate n blocks, hash them (a computed prefix), note the owner (as the KVCacheManager.free wrapper
    does), free them in reverse order (as SingleTypeKVCacheManager.free does). Returns the block ids."""
    bl = pool.get_new_blocks(n)
    if cache:
        for b in bl:
            give_hash(pool, b)
    if task is not None:
        for b in bl:
            q.note_owner(b, task)
    pool.free_blocks(reversed(bl))
    return ids(bl)


# ---------------------------------------------------------------- 1. equivalence with vLLM's queue
def test_same_order_as_vllm_untagged():
    for seed in (0, 1, 2):
        same_order_as_vllm(seed, "untagged")


def test_same_order_as_vllm_tag_only():
    for seed in (0, 1, 2):
        same_order_as_vllm(seed, "tag_only")


def same_order_as_vllm(seed, mode):
    """With no task tags (or tags but both policies off = DBKV_TASKEVICT_MODE=tag_only), the tiered queue
    hands out and orders blocks exactly like vLLM's single FreeKVCacheBlockQueue, under random alloc /
    cache / touch (prefix hit, incl. shared blocks) / free / unpin sequences."""
    rng = random.Random(seed)
    n = 97
    stock = BlockPool(num_gpu_blocks=n, enable_caching=True, hash_block_size=16)
    live = Live()
    kw = dict(use_ended=False, use_paused=False) if mode == "tag_only" else {}
    tp, q = tiered_pool(n, live, **kw)
    held = []   # list of (task, [block ids]) per running "request"
    tasks = ["A", "B", "C", "D"]
    n_ops = dict(free=0, unpin=0, evict=0)
    for step in range(4000):
        op = rng.random()
        if op < 0.30:
            k = rng.randint(1, 8)
            if stock.get_num_free_blocks() >= k:
                n_ops["evict"] += sum(stock.blocks[i].block_hash is not None
                                      for i in ids(stock.free_block_queue.get_all_free_blocks()[:k]))
                a, b = stock.get_new_blocks(k), tp.get_new_blocks(k)
                assert ids(a) == ids(b), step
                held.append((rng.choice(tasks), ids(a)))
        elif op < 0.45 and held:
            _, bl = rng.choice(held)
            for bid in bl:
                if stock.blocks[bid].block_hash is None and rng.random() < 0.7:
                    _h[0] += 1
                    key = make_block_hash_with_group_id(BlockHash(_h[0].to_bytes(32, "big")), 0)
                    stock._insert_block_hash(key, stock.blocks[bid], None)
                    tp._insert_block_hash(key, tp.blocks[bid], None)
        elif op < 0.60:
            # prefix hit: touch some cached blocks (free or in use) into a new or existing request
            cached = [b.block_id for b in stock.blocks[1:] if b.block_hash is not None]
            if cached:
                pick = rng.sample(cached, min(len(cached), rng.randint(1, 4)))
                stock.touch([stock.blocks[i] for i in pick])
                tp.touch([tp.blocks[i] for i in pick])
                held.append((rng.choice(tasks), pick))
        elif op < 0.90 and held:
            task, bl = held.pop(rng.randrange(len(held)))
            if mode == "tag_only":
                for bid in bl:
                    q.note_owner(tp.blocks[bid], task)
            stock.free_blocks(reversed([stock.blocks[i] for i in bl]))
            tp.free_blocks(reversed([tp.blocks[i] for i in bl]))
            n_ops["free"] += 1
        elif op < 0.95 and held:
            # offload path: release to the tail, stay readable until reused
            _, bl = held.pop(rng.randrange(len(held)))
            stock.unpin_blocks([stock.blocks[i] for i in bl], lambda b: None)
            tp.unpin_blocks([tp.blocks[i] for i in bl], lambda b: None)
            n_ops["unpin"] += 1
        elif mode == "tag_only":
            t = rng.choice(tasks)
            live.dead.add(t)
            q.on_task_gone(t, ended=True)
            tasks[tasks.index(t)] = t + "'"
        assert stock.get_num_free_blocks() == tp.get_num_free_blocks(), step
        assert ids(stock.free_block_queue.get_all_free_blocks()) == ids(q.get_all_free_blocks()), step
        if step % 200 == 0:
            q.check()
    q.check()
    assert n_ops["free"] > 500 and n_ops["unpin"] > 50 and n_ops["evict"] > 100, n_ops
    assert sum(q.n_evict) == n_ops["evict"], (q.n_evict, n_ops)


def test_iter_blocks_after_matches_get_all():
    p, q = tiered_pool(33)
    run_request(p, q, 5, "A")
    run_request(p, q, 5, None)
    lst = q.get_all_free_blocks()
    assert ids(q.iter_blocks_after(None)) == ids(lst)
    for k in (0, 3, 20, len(lst) - 1):
        assert ids(q.iter_blocks_after(lst[k])) == ids(lst[k + 1:])


# ---------------------------------------------------------------- 2. the policy
def test_eviction_order_ended_then_untagged_then_paused():
    """(i) ended task's blocks go first, (ii) a paused live task's blocks last; stock LRU would evict the
    paused task (it freed earlier than the untagged request)."""
    live = Live()
    p, q = tiered_pool(41, live)            # 40 usable blocks
    a = run_request(p, q, 8, "A")           # task A, will end
    b = run_request(p, q, 8, "B")           # task B, paused (live)
    c = run_request(p, q, 8, None)          # untagged
    live.dead.add("A")
    assert q.on_task_gone("A", ended=True) == 8   # A's free blocks: PAUSED -> ENDED
    q.check()
    assert q.snapshot()["free"] == dict(first=16, ended=8, normal=8, paused=8)
    order = ids(q.get_all_free_blocks())
    assert order[16:24] == a[::-1]          # tail first, as vLLM frees
    assert order[24:32] == c[::-1]
    assert order[32:] == b[::-1]
    got = ids(p.get_new_blocks(16 + 8 + 4))
    assert set(a) <= set(got) and not set(b) & set(got)
    assert q.snapshot()["evicted"] == dict(first=0, ended=8, normal=4, paused=0)
    for bid in b:                           # B's prefix is still in the prefix cache
        assert p.blocks[bid].block_hash is not None
    q.check()

    # the same sequence on stock vLLM: LRU evicts A then B (B freed before C)
    s = BlockPool(num_gpu_blocks=41, enable_caching=True, hash_block_size=16)
    for _ in range(3):
        bl = s.get_new_blocks(8)
        for x in bl:
            give_hash(s, x)
        s.free_blocks(reversed(bl))
    got = ids(s.get_new_blocks(28))
    assert set(b[::-1][:4]) <= set(got)     # stock evicts 4 of the paused task's blocks


def test_shared_block_protected_while_any_owner_lives():
    live = Live()
    p, q = tiered_pool(21, live)
    bl = p.get_new_blocks(4)
    for x in bl:
        give_hash(p, x)
    p.touch(bl[:2])                         # B hits A's first two blocks (shared prefix: system prompt)
    for x in bl:
        q.note_owner(x, "A")
    p.free_blocks(reversed(bl))             # A's request ends its turn
    for x in bl[:2]:
        q.note_owner(x, "B")
    p.free_blocks(reversed(bl[:2]))         # B's request ends its turn
    q.check()
    assert all(q.tier_of[x.block_id] == PAUSED for x in bl)
    live.dead.add("A")
    q.on_task_gone("A", ended=True)
    assert [q.tier_of[x.block_id] for x in bl] == [PAUSED, PAUSED, ENDED, ENDED]
    live.dead.add("B")
    q.on_task_gone("B", ended=True)
    # shared by two tasks that both ended: plain LRU (a common prefix may serve the next task)
    assert [q.tier_of[x.block_id] for x in bl] == [NORMAL, NORMAL, ENDED, ENDED]
    q.check()


def test_free_after_end_goes_straight_to_ended():
    live = Live()
    p, q = tiered_pool(21, live)
    live.dead.add("A")                      # task_end processed before the last request's (deferred) free
    a = run_request(p, q, 3, "A")
    assert all(q.tier_of[x] == ENDED for x in a)
    assert q.task_blocks == {}
    q.check()


def test_touch_from_paused_tier_and_refree():
    live = Live()
    p, q = tiered_pool(21, live)
    a = run_request(p, q, 5, "A")           # turn 1
    p.touch([p.blocks[x] for x in a])       # turn 2 hits the whole prefix
    q.check()
    assert q.snapshot()["free"]["paused"] == 0
    extra = p.get_new_blocks(2)
    for x in extra:
        give_hash(p, x)
    allb = [p.blocks[x] for x in a] + extra
    for x in allb:
        q.note_owner(x, "A")
    p.free_blocks(reversed(allb))
    assert q.snapshot()["free"]["paused"] == 7
    assert not any(q.flags[x.block_id] & 2 for x in allb)   # same task twice is not "shared"
    q.check()


def test_unhashed_blocks_are_used_first_and_forgotten():
    p, q = tiered_pool(11)
    bl = p.get_new_blocks(3)               # never hashed (e.g. a partial last block)
    for x in bl:
        q.note_owner(x, "A")
    p.free_blocks(reversed(bl))
    assert all(q.tier_of[x.block_id] == FIRST for x in bl)
    assert ids(q.get_all_free_blocks())[:3] == ids(bl)[::-1]  # freed tail-first, prepended in that order
    assert q.task_blocks == {} and q.flags == {}
    q.check()


def test_reset_prefix_cache():
    p, q = tiered_pool(21)
    run_request(p, q, 5, "A")
    run_request(p, q, 5, None)
    assert p.reset_prefix_cache()
    q.reset()                               # what the plugin's reset_prefix_cache wrapper does
    assert q.snapshot()["free"] == dict(first=20, ended=0, normal=0, paused=0)
    assert q.task_blocks == {}
    q.check()


# ---------------------------------------------------------------- 3. registry: TTL, end channel
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_registry_ttl_and_end():
    clk = Clock()
    reg = TaskRegistry(ttl=5, clock=clk)
    p, q = tiered_pool(31, reg.is_live)
    reg.queues.append(q)
    reg.on_request_added("A"); reg.on_request_added("B"); reg.on_request_added("C")
    a = run_request(p, q, 4, "A"); reg.on_request_finished("A")
    b = run_request(p, q, 4, "B"); reg.on_request_finished("B")
    run_request(p, q, 4, "C")              # C's request is still in flight (no finish): never expires
    clk.t += 3
    reg.tick()
    assert all(q.tier_of[x] == PAUSED for x in a + b)
    reg.post_end("A")
    clk.t += 3                              # B idle 6 s > TTL 5
    reg.tick()
    assert all(q.tier_of[x] == ENDED for x in a)
    assert all(q.tier_of[x] == NORMAL for x in b)     # expired: back to plain LRU, not "ended"
    assert reg.counts["expirations"] == 1 and "C" in reg.last_seen
    reg.on_request_added("B")               # B comes back after its DB call
    assert reg.counts["revived"] == 1 and reg.is_live("B")
    reg.post_end("A"); reg.post_end("Z")
    reg.tick()
    assert reg.counts["end_dup"] == 1 and reg.counts["end_unseen"] == 1
    q.check()


def test_listener_roundtrip():
    reg = TaskRegistry(ttl=0)
    srv = reg.start_listener("127.0.0.1", 0)
    port = srv.server_address[1]
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/task_end", data=json.dumps({"task_id": "t00001"}).encode(),
            headers={"Content-Type": "application/json"}), timeout=5)
        assert json.loads(r.read())["ok"]
        r = urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/task_end", data=json.dumps({"task_ids": ["t2", "t3"]}).encode()),
            timeout=5)
        assert json.loads(r.read())["n"] == 2
        reg.on_request_added("t2")
        reg.tick()
        assert not reg.is_live("t00001") and not reg.is_live("t2") and reg.counts["end_msgs"] == 3
        s = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/stats", timeout=5).read())
        assert s["ended"] == 3
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- 4. cost of the bookkeeping
def test_overhead_alloc_free_cycle():
    """One agent turn at 32B scale: a request holds ~320 blocks (5k tokens); hit the paused prefix, add 10
    blocks, note owners, free. Prints us per turn, stock vs tiered (informative; the bound is loose)."""
    import time as _t

    def cycle(pool, q, tagged, n_turns=300):
        prefix = pool.get_new_blocks(310)
        for b in prefix:
            give_hash(pool, b)
        pool.free_blocks(reversed(prefix))
        t0 = _t.perf_counter()
        for _ in range(n_turns):
            pool.touch(prefix)
            new = pool.get_new_blocks(10)
            for b in new:
                give_hash(pool, b)
            allb = prefix + new
            if tagged:
                for b in allb:
                    q.note_owner(b, "T")
            pool.free_blocks(reversed(allb))
        return (_t.perf_counter() - t0) / n_turns * 1e6

    stock = BlockPool(num_gpu_blocks=19084, enable_caching=True, hash_block_size=16)  # 305,328 / 16
    us_stock = cycle(stock, None, False)
    tp, q = tiered_pool(19084)
    us_tiered = cycle(tp, q, True)
    q.check()
    print(f"  per-turn alloc/free cycle (320 blocks): stock {us_stock:.0f} us, tiered+tagged {us_tiered:.0f} us")
    assert us_tiered < 6 * us_stock + 500
