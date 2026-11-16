"""Task-tiered free-block queue: a drop-in replacement for vLLM's FreeKVCacheBlockQueue (PLAN 2j option E).

vLLM V1 keeps every free KV block (including blocks that still hold a cached prefix, ref_cnt == 0) in ONE
doubly linked list, `BlockPool.free_block_queue`. Allocation pops from the front; that pop is the eviction.
Hash-less blocks are prepended (reused first), cached blocks are appended (LRU). See
vllm/v1/core/block_pool.py: get_new_blocks / free_blocks / touch, and kv_cache_utils.FreeKVCacheBlockQueue.

This class keeps four such lists ("tiers") and pops them in order:

    FIRST  hash-less blocks (vLLM's own "evict first": prepend_n), plus the initial never-used blocks
    ENDED  cached blocks whose every owner task has ended (POST task_end)       -> policy (i)
    NORMAL cached blocks with no task tag, shared by >= 2 tasks that all left, or whose owner hit the TTL
    PAUSED cached blocks of at least one live (paused) task, LRU among them     -> policy (ii)

With no task tags at all, ENDED and PAUSED stay empty and FIRST ++ NORMAL is exactly vLLM's single list
(tests/test_queue.py checks this against the real class under random operation sequences).

Each tier is itself a vLLM FreeKVCacheBlockQueue (the class is passed in, so this module does not import
vLLM), so the per-block prev/next pointer discipline is vLLM's own code. Metadata is per block id:
  live_owners[bid]  set of live task ids that held this block when one of their requests freed it
  flags[bid]        TAGGED (some task held it), SHARED (>= 2 distinct tasks), KEEP (an owner expired by TTL)
  task_blocks[t]    ordered set (dict) of block ids task t held, to re-tier them when t ends or expires.
Metadata is dropped when the block is popped (re-used = evicted) or on reset().
"""

FIRST, ENDED, NORMAL, PAUSED = 0, 1, 2, 3
TIER_NAMES = ("first", "ended", "normal", "paused")
NOT_FREE = 255
F_TAGGED, F_SHARED, F_KEEP = 1, 2, 4


class TaskTieredFreeQueue:
    """Same interface as vLLM 0.33's FreeKVCacheBlockQueue (num_free_blocks, popleft, popleft_n, remove,
    append, append_n, prepend_n, get_all_free_blocks, iter_blocks_after), plus note_owner / on_task_gone /
    reset / snapshot for the task policy."""

    def __init__(self, base, blocks, is_live, queue_cls=None, use_ended=True, use_paused=True):
        """base: the pool's existing FreeKVCacheBlockQueue (its order is kept, all in FIRST);
        blocks: BlockPool.blocks (block_id -> KVCacheBlock); is_live(task) -> bool."""
        cls = queue_cls or type(base)
        self._cls = cls
        self.blocks = blocks
        self.is_live = is_live
        self.use_ended, self.use_paused = use_ended, use_paused
        self.tier_of = bytearray([NOT_FREE]) * len(blocks)
        self.tiers = [cls([]) for _ in TIER_NAMES]
        init = base.get_all_free_blocks()
        self.tiers[FIRST].append_n(init)
        for b in init:
            self.tier_of[b.block_id] = FIRST
        self.live_owners = {}
        self.flags = {}
        self.task_blocks = {}
        self.n_pop = [0] * 4       # blocks handed out from each tier
        self.n_evict = [0] * 4     # ... of which still held a cached prefix (true evictions)
        self.n_moved = 0           # PAUSED -> ENDED/NORMAL moves on task end / expiry

    # ---------------- FreeKVCacheBlockQueue interface ----------------
    @property
    def num_free_blocks(self):
        t = self.tiers
        return t[0].num_free_blocks + t[1].num_free_blocks + t[2].num_free_blocks + t[3].num_free_blocks

    def _on_pop(self, b, i):
        bid = b.block_id
        self.tier_of[bid] = NOT_FREE
        self.n_pop[i] += 1
        if b.block_hash is not None:
            self.n_evict[i] += 1
        self._forget(bid)

    def popleft(self):
        for i, t in enumerate(self.tiers):
            if t.num_free_blocks:
                b = t.popleft()
                self._on_pop(b, i)
                return b
        raise ValueError("No free blocks available")

    def popleft_n(self, n):
        if n == 0:
            return []
        assert self.num_free_blocks >= n
        ret = []
        for i, t in enumerate(self.tiers):
            k = min(n, t.num_free_blocks)
            if k:
                got = t.popleft_n(k)
                for b in got:
                    self._on_pop(b, i)
                ret.extend(got)
                n -= k
                if n == 0:
                    break
        return ret

    def remove(self, block):
        """A free block was hit by a new request (BlockPool.touch): it leaves the free list, metadata stays."""
        i = self.tier_of[block.block_id]
        if i == NOT_FREE:
            raise RuntimeError(f"remove() called on an invalid block: {block}")
        self.tiers[i].remove(block)
        self.tier_of[block.block_id] = NOT_FREE

    def append(self, block):
        self.append_n([block])

    def append_n(self, blocks):
        if not blocks:
            return
        per = [None, None, None, None]
        for b in blocks:
            i = self._tier(b)
            if per[i] is None:
                per[i] = []
            per[i].append(b)
            self.tier_of[b.block_id] = i
        for i, lst in enumerate(per):
            if lst:
                self.tiers[i].append_n(lst)

    def prepend_n(self, blocks):
        if not blocks:
            return
        for b in blocks:
            self.tier_of[b.block_id] = FIRST
            self._forget(b.block_id)  # hash-less: nothing left to protect
        self.tiers[FIRST].prepend_n(blocks)

    def get_all_free_blocks(self):
        out = []
        for t in self.tiers:
            out.extend(t.get_all_free_blocks())
        return out

    def iter_blocks_after(self, cursor):
        if cursor is None:
            start = 0
        else:
            i = self.tier_of[cursor.block_id]
            if i == NOT_FREE:  # stale cursor: vLLM's list yields nothing either
                return
            yield from self.tiers[i].iter_blocks_after(cursor)
            start = i + 1
        for t in self.tiers[start:]:
            yield from t.iter_blocks_after(None)

    # ---------------- task policy ----------------
    def _tier(self, b):
        if b.block_hash is None:
            return NORMAL  # only via unpin_blocks (offload path); vLLM appends these to the tail too
        bid = b.block_id
        if self.use_paused and self.live_owners.get(bid):
            return PAUSED
        f = self.flags.get(bid, 0)
        if f & (F_SHARED | F_KEEP):
            return NORMAL
        if f & F_TAGGED and self.use_ended:
            return ENDED
        return NORMAL

    def _forget(self, bid):
        owners = self.live_owners.pop(bid, None)
        if owners:
            for t in owners:
                s = self.task_blocks.get(t)
                if s is not None:
                    s.pop(bid, None)
                    if not s:
                        del self.task_blocks[t]
        self.flags.pop(bid, None)

    def note_owner(self, block, task):
        """Called (via the KVCacheManager.free / pop_blocks_for_free wrappers) for every block a request of
        `task` holds, just before the request frees it."""
        bid = block.block_id
        f = self.flags.get(bid, 0)
        live = self.live_owners.get(bid)
        if f & F_TAGGED and not (live and task in live):
            f |= F_SHARED
        self.flags[bid] = (f | F_TAGGED) & ~F_KEEP
        if self.is_live(task):
            if live is None:
                self.live_owners[bid] = {task}
            else:
                live.add(task)
            self.task_blocks.setdefault(task, {})[bid] = None

    def on_task_gone(self, task, ended):
        """task ended (ended=True: policy (i)) or expired by TTL (ended=False: back to plain LRU).
        Its free blocks that no other live task holds leave the PAUSED tier."""
        bids = self.task_blocks.pop(task, None)
        if not bids:
            return 0
        moved = 0
        for bid in reversed(list(bids)):  # later-turn (tail) blocks first, as vLLM frees tail-first
            s = self.live_owners.get(bid)
            if s is not None:
                s.discard(task)
                if s:
                    continue
                del self.live_owners[bid]
            if not ended:
                self.flags[bid] = self.flags.get(bid, 0) | F_KEEP
            if self.tier_of[bid] == PAUSED:
                b = self.blocks[bid]
                self.tiers[PAUSED].remove(b)
                i = self._tier(b)
                self.tiers[i].append_n([b])
                self.tier_of[bid] = i
                moved += 1
        self.n_moved += moved
        return moved

    def reset(self):
        """After BlockPool.reset_prefix_cache(): every hash is gone, so all free blocks go back to FIRST."""
        allb = self.get_all_free_blocks()
        self.tiers = [self._cls([]) for _ in TIER_NAMES]
        self.tiers[FIRST].append_n(allb)
        self.tier_of = bytearray([NOT_FREE]) * len(self.blocks)
        for b in allb:
            self.tier_of[b.block_id] = FIRST
        self.live_owners.clear()
        self.flags.clear()
        self.task_blocks.clear()

    def snapshot(self):
        return dict(free={n: t.num_free_blocks for n, t in zip(TIER_NAMES, self.tiers)},
                    popped=dict(zip(TIER_NAMES, self.n_pop)), evicted=dict(zip(TIER_NAMES, self.n_evict)),
                    moved=self.n_moved, tasks_with_blocks=len(self.task_blocks),
                    blocks_with_live_owner=len(self.live_owners))

    def check(self):
        """Invariants, for tests: tier counts match list walks and tier_of; every free block is in one tier."""
        seen = set()
        for i, t in enumerate(self.tiers):
            lst = t.get_all_free_blocks()
            assert len(lst) == t.num_free_blocks, (TIER_NAMES[i], len(lst), t.num_free_blocks)
            for b in lst:
                assert self.tier_of[b.block_id] == i, (b.block_id, self.tier_of[b.block_id], i)
                assert b.block_id not in seen
                seen.add(b.block_id)
        for bid, i in enumerate(self.tier_of):
            assert (i == NOT_FREE) == (bid not in seen), bid
        for t, bids in self.task_blocks.items():
            for bid in bids:
                assert t in self.live_owners.get(bid, ()), (t, bid)
        return True
