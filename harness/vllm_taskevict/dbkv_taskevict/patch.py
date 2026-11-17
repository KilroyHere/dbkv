"""Monkeypatches into vLLM 0.33 V1 (no file of the installed package is modified).

  BlockPool.__init__            replace free_block_queue by TaskTieredFreeQueue (caching pools only)
  BlockPool.reset_prefix_cache  on success, put every free block back into tier FIRST and forget task state
  KVCacheManager.free           note the request's task as owner of its blocks, then vLLM frees them
  KVCacheManager.pop_blocks_for_free   same, for the deferred-free path (async scheduling)
  Scheduler.__init__            start the task_end listener once; warn if the policy is not "priority"
  Scheduler.add_request         count the task's request; an in-band {"dbkv_task_end": id} ends a task
  Scheduler._free_request       the task's request finished (for the TTL's "nothing in flight" test)
  Scheduler.schedule            registry.tick() first: drain task_end messages, TTL expiry, stats line

Preemption (policy iii) needs no patch: with `--scheduling-policy priority` vLLM already preempts
max(running, key=(priority, arrival_time)), and the gateway sets priority = task start (ms since gateway
start), so the victim is the request of the youngest task (vllm/v1/core/sched/scheduler.py, schedule()).
"""
import logging, os

from .tiers import TaskTieredFreeQueue

log = logging.getLogger("dbkv_taskevict")

TASK_KEY, END_KEY = "dbkv_task", "dbkv_task_end"


def _xargs(request):
    sp = getattr(request, "sampling_params", None)
    return getattr(sp, "extra_args", None) if sp is not None else None


def task_of(request):
    ea = _xargs(request)
    if not ea:
        return None
    t = ea.get(TASK_KEY)
    return None if t is None else str(t)


def note_request_blocks(mgr, request):
    t = task_of(request)
    if t is None:
        return
    for group in mgr.coordinator.get_blocks(request.request_id):
        for b in group:
            if b.is_null:
                continue
            q = (b.pool if b.pool is not None else mgr.block_pool).free_block_queue
            if type(q) is TaskTieredFreeQueue:
                q.note_owner(b, t)


def install(reg, cfg):
    from vllm.v1.core.block_pool import BlockPool
    from vllm.v1.core.kv_cache_manager import KVCacheManager
    from vllm.v1.core.sched.scheduler import Scheduler

    if getattr(BlockPool, "_dbkv_taskevict", False):
        return False
    import vllm
    from vllm.v1.core.kv_cache_utils import FreeKVCacheBlockQueue
    if not str(vllm.__version__).startswith("0.33."):
        log.warning("dbkv_taskevict: written and tested against vLLM 0.33.0, found %s", vllm.__version__)
    for m in ("popleft", "popleft_n", "remove", "append", "append_n", "prepend_n", "get_all_free_blocks",
              "iter_blocks_after"):
        if not hasattr(FreeKVCacheBlockQueue, m):
            raise RuntimeError(f"dbkv_taskevict: FreeKVCacheBlockQueue.{m} missing; vLLM internals changed")
    for cls, m in ((KVCacheManager, "pop_blocks_for_free"), (Scheduler, "_free_request"), (BlockPool, "touch")):
        if not hasattr(cls, m):
            raise RuntimeError(f"dbkv_taskevict: {cls.__name__}.{m} missing; vLLM internals changed")

    bp_init = BlockPool.__init__

    def BlockPool__init__(self, *a, **k):
        bp_init(self, *a, **k)
        if self.enable_caching:
            q = TaskTieredFreeQueue(self.free_block_queue, self.blocks, reg.is_live,
                                    use_ended=cfg["use_ended"], use_paused=cfg["use_paused"])
            self.free_block_queue = q
            reg.queues.append(q)
            log.info("dbkv_taskevict: tiered free queue on a pool of %d blocks (mode=%s)",
                     self.num_gpu_blocks, cfg["mode"])

    bp_reset = BlockPool.reset_prefix_cache

    def reset_prefix_cache(self):
        ok = bp_reset(self)
        if ok and type(self.free_block_queue) is TaskTieredFreeQueue:
            self.free_block_queue.reset()
            reg.reset_tasks()
        return ok

    km_free = KVCacheManager.free

    def free(self, request):
        note_request_blocks(self, request)
        return km_free(self, request)

    km_pop = KVCacheManager.pop_blocks_for_free

    def pop_blocks_for_free(self, request):
        note_request_blocks(self, request)
        return km_pop(self, request)

    s_init = Scheduler.__init__

    def Scheduler__init__(self, *a, **k):
        s_init(self, *a, **k)
        pol = getattr(getattr(self, "policy", None), "value", None)
        if pol != "priority":
            log.warning("dbkv_taskevict: scheduling policy is %r; task-aware preemption (lowest-priority = "
                        "youngest task) needs --scheduling-policy priority and the gateway's --priority", pol)
        if cfg["port"] and reg.listener is None:
            try:
                reg.start_listener(cfg["host"], cfg["port"])
                log.info("dbkv_taskevict: task_end listener on http://%s:%s/task_end", cfg["host"], cfg["port"])
            except OSError as e:
                log.warning("dbkv_taskevict: listener on %s:%s failed (%r); only the in-band task_end works",
                            cfg["host"], cfg["port"], e)

    s_add = Scheduler.add_request

    def add_request(self, request):
        ea = _xargs(request)
        new = request.request_id not in self.requests
        s_add(self, request)
        if ea:
            end = ea.get(END_KEY)
            if end is not None:
                reg.post_end(end)
            t = ea.get(TASK_KEY)
            if t is not None and new:
                reg.on_request_added(str(t))

    s_free_req = Scheduler._free_request

    def _free_request(self, request, *a, **k):
        r = s_free_req(self, request, *a, **k)
        t = task_of(request)
        if t is not None:
            reg.on_request_finished(t)
        return r

    s_sched = Scheduler.schedule

    def schedule(self, *a, **k):
        reg.tick()
        return s_sched(self, *a, **k)

    BlockPool.__init__ = BlockPool__init__
    BlockPool.reset_prefix_cache = reset_prefix_cache
    KVCacheManager.free = free
    KVCacheManager.pop_blocks_for_free = pop_blocks_for_free
    Scheduler.__init__ = Scheduler__init__
    Scheduler.add_request = add_request
    Scheduler._free_request = _free_request
    Scheduler.schedule = schedule
    BlockPool._dbkv_taskevict = True
    return True


def config_from_env(env=os.environ):
    mode = env.get("DBKV_TASKEVICT_MODE", "full")
    if mode not in ("full", "ended_only", "paused_only", "tag_only"):
        raise ValueError(f"DBKV_TASKEVICT_MODE={mode!r}: full | ended_only | paused_only | tag_only")
    return dict(mode=mode,
                use_ended=mode in ("full", "ended_only"),
                use_paused=mode in ("full", "paused_only"),
                ttl=float(env.get("DBKV_TASKEVICT_TTL", "300")),
                host=env.get("DBKV_TASKEVICT_HOST", "127.0.0.1"),
                port=int(env.get("DBKV_TASKEVICT_PORT", "8899")),
                log=env.get("DBKV_TASKEVICT_LOG", ""),
                log_every=float(env.get("DBKV_TASKEVICT_LOG_EVERY", "10")))
