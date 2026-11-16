"""The installed plugin end to end on vLLM's real KVCacheManager (CPU, no model): a paused task's prefix
survives churn by short tasks that end, where stock LRU loses it.

The patches are class-level, so the scenario runs in a subprocess (it would otherwise change the stock
BlockPool used by test_tiers.py).
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)


def test_plugin_scenario_subprocess():
    env = dict(os.environ, DBKV_TASKEVICT="1", DBKV_TASKEVICT_PORT="0", DBKV_TASKEVICT_TTL="0",
               PYTHONPATH=PKG + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True,
                       timeout=600)
    print(r.stdout[-4000:])
    print(r.stderr[-4000:])
    assert r.returncode == 0
    assert "SCENARIO OK" in r.stdout


def main():
    import dbkv_taskevict
    from dbkv_taskevict.tiers import TaskTieredFreeQueue
    dbkv_taskevict.register()
    reg = dbkv_taskevict.REGISTRY
    assert reg is not None

    import torch
    from vllm.sampling_params import SamplingParams
    from vllm.utils.hashing import sha256
    from vllm.v1.core.block_pool import BlockPool
    from vllm.v1.core.kv_cache_manager import KVCacheManager
    from vllm.v1.core.kv_cache_utils import get_request_block_hasher, init_none_hash
    from vllm.v1.core.sched.scheduler import Scheduler
    from vllm.v1.kv_cache_interface import FullAttentionSpec, KVCacheConfig, KVCacheGroupSpec
    from vllm.v1.request import Request

    assert getattr(BlockPool, "_dbkv_taskevict", False)
    assert Scheduler.schedule.__name__ == "schedule" and Scheduler.schedule.__module__ == "dbkv_taskevict.patch"
    assert dbkv_taskevict.register() is None and len(reg.queues) == 0   # idempotent

    BS = 16
    init_none_hash(sha256)
    hasher = get_request_block_hasher(BS, sha256)
    spec = FullAttentionSpec(block_size=BS, num_kv_heads=1, head_size=8, dtype=torch.float16)

    def manager(nblocks):
        cfg = KVCacheConfig(num_blocks=nblocks, kv_cache_tensors=[],
                            kv_cache_groups=[KVCacheGroupSpec(["layer.0"], spec)])
        return KVCacheManager(cfg, max_model_len=8192, scheduler_block_size=BS, hash_block_size=BS,
                              enable_caching=True)

    seq = [0]

    def turn(mgr, tokens, task, deferred=False):
        seq[0] += 1
        xa = {"dbkv_task": task} if task else None
        req = Request(f"r{seq[0]}", list(tokens), SamplingParams(max_tokens=1, extra_args=xa), None,
                      block_hasher=hasher)
        computed, n_hit, *_ = mgr.get_computed_blocks(req)
        new = mgr.allocate_slots(req, len(tokens) - n_hit, n_hit, computed)
        assert new is not None, "pool too small"
        req.num_computed_tokens = len(tokens)
        if deferred:   # async-scheduling path: pop now, return to the pool later
            blocks = mgr.pop_blocks_for_free(req)
            mgr.block_pool.free_blocks(reversed(blocks))
        else:
            mgr.free(req)
        return n_hit

    def toks(base, n):
        return [base * 100003 % 50000 + i % 997 + 1 for i in range(n)]

    def scenario(tagged):
        mgr = manager(64)                       # 63 usable blocks x 16 tokens
        q = mgr.block_pool.free_block_queue
        assert type(q) is TaskTieredFreeQueue
        P1 = toks(1, 20 * BS)                   # paused task P, turn 1: 20 blocks
        turn(mgr, P1, "P" if tagged else None)
        reg.on_request_added("P") if tagged else None
        for i in range(10):                     # 10 short tasks, 16 blocks each, end right away
            t = f"X{i}"
            turn(mgr, toks(10 + i, 16 * BS), t if tagged else None, deferred=(i % 2 == 1))
            if tagged:
                reg.post_end(t)
                reg.tick()
        q.check()
        hit = turn(mgr, P1 + toks(99, 2 * BS), "P" if tagged else None)   # P resumes after its tool call
        return hit, q.snapshot()

    hit_stock, snap_stock = scenario(tagged=False)
    hit_e, snap_e = scenario(tagged=True)
    print("stock-order hit tokens:", hit_stock, snap_stock)
    print("task-aware hit tokens:", hit_e, snap_e)
    assert hit_stock < 20 * BS
    assert hit_e == 20 * BS
    assert snap_e["evicted"]["paused"] == 0 and snap_e["evicted"]["ended"] > 0
    assert reg.counts["end_msgs"] == 10

    # reset_prefix_cache wrapper
    mgr = manager(32)
    turn(mgr, toks(5, 4 * BS), "R")
    assert mgr.block_pool.reset_prefix_cache()
    assert mgr.block_pool.free_block_queue.snapshot()["free"]["first"] == 31
    assert reg.counts.get("resets") == 1 and not reg.ended and not reg.last_seen
    print("SCENARIO OK")


if __name__ == "__main__":
    main()
