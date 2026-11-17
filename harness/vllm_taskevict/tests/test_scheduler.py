"""The plugin inside vLLM's real V1 Scheduler (CPU, no model weights: only the cached Qwen3-8B config is
read, HF offline). Exercises the Scheduler wrappers: add_request (task tag, in-band end), schedule (tick),
_free_request, and KVCacheManager.free reached through the scheduler. Runs in a subprocess (class patches).
If vLLM cannot build a config on this machine, the test reports SKIP rather than FAIL.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)


def test_scheduler_subprocess():
    env = dict(os.environ, DBKV_TASKEVICT="1", DBKV_TASKEVICT_PORT="0", DBKV_TASKEVICT_TTL="0",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               PYTHONPATH=PKG + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env, capture_output=True, text=True,
                       timeout=900)
    out = r.stdout + r.stderr
    print(r.stdout[-3000:])
    if "SETUP FAILED" in r.stdout:
        print("SKIP: could not build a vLLM Scheduler here:\n" + r.stderr[-3000:])
        return
    print(r.stderr[-3000:])
    assert r.returncode == 0 and "SCHED OK" in out


def main():
    import dbkv_taskevict
    dbkv_taskevict.register()
    reg = dbkv_taskevict.REGISTRY
    try:
        import torch
        from vllm.config import CacheConfig, DeviceConfig, ModelConfig, SchedulerConfig, VllmConfig
        from vllm.sampling_params import SamplingParams
        from vllm.utils.hashing import sha256
        from vllm.v1.core.kv_cache_utils import get_request_block_hasher, init_none_hash
        from vllm.v1.core.sched.scheduler import Scheduler
        from vllm.v1.kv_cache_interface import FullAttentionSpec, KVCacheConfig, KVCacheGroupSpec
        from vllm.v1.request import Request, RequestStatus
        from vllm.v1.structured_output import StructuredOutputManager

        from vllm.v1.outputs import ModelRunnerOutput

        BS = 16

        def make_scheduler(NB):
            model_config = ModelConfig(model="Qwen/Qwen3-8B", dtype="bfloat16", seed=0, max_model_len=2048)
            sched_config = SchedulerConfig(max_num_seqs=16, max_num_batched_tokens=4096, max_model_len=2048,
                                           is_encoder_decoder=False, policy="priority")
            cache_config = CacheConfig(block_size=BS, gpu_memory_utilization=0.9, cache_dtype="auto",
                                       enable_prefix_caching=True)
            cache_config.num_gpu_blocks = NB
            vcfg = VllmConfig(scheduler_config=sched_config, model_config=model_config, cache_config=cache_config,
                              device_config=DeviceConfig(device="cpu"))
            kv = KVCacheConfig(num_blocks=NB, kv_cache_tensors=[], kv_cache_groups=[KVCacheGroupSpec(
                ["layer.0"], FullAttentionSpec(block_size=BS, num_kv_heads=1, head_size=8, dtype=torch.bfloat16))])
            return Scheduler(vcfg, kv, StructuredOutputManager(vcfg), block_size=BS, log_stats=True)

        sch = make_scheduler(64)
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("SETUP FAILED")
        sys.exit(0)

    init_none_hash(sha256)
    hasher = get_request_block_hasher(BS, sha256)
    q = sch.kv_cache_manager.block_pool.free_block_queue
    assert type(q).__name__ == "TaskTieredFreeQueue"
    n = [0]

    def req(tokens, xa, prio=0):
        n[0] += 1
        return Request(f"q{n[0]}", tokens, SamplingParams(max_tokens=4, extra_args=xa), None, priority=prio,
                       block_hasher=hasher)

    def run_turn(r):
        sch.add_request(r)
        out = sch.schedule()
        assert r.request_id in out.num_scheduled_tokens, out.num_scheduled_tokens
        sch.finish_requests(r.request_id, RequestStatus.FINISHED_ABORTED)

    P = [7 + i % 50 for i in range(10 * BS)]
    run_turn(req(P, {"dbkv_task": "P", "dbkv_task_start": 1.0}, prio=1))
    assert reg.last_seen.get("P") is not None and reg.inflight.get("P") == 0
    assert q.snapshot()["free"]["paused"] == 10, q.snapshot()
    X = [900 + i % 70 for i in range(12 * BS)]
    run_turn(req(X, {"dbkv_task": "X", "dbkv_task_start": 2.0}, prio=2))
    assert q.snapshot()["free"]["paused"] == 22
    # in-band end of X: a tiny request carrying {"dbkv_task_end": "X"}; schedule() drains it
    sch.add_request(req([1, 2, 3], {"dbkv_task_end": "X"}))
    sch.schedule()
    assert not reg.is_live("X") and reg.counts["end_msgs"] == 1
    snap = q.snapshot()
    assert snap["free"]["ended"] == 12 and snap["free"]["paused"] == 10, snap
    # out-of-band end of P via the registry inbox (what the HTTP listener does)
    reg.post_end("P")
    r = req([5, 6, 7], None)
    run_turn(r)
    assert not reg.is_live("P") and q.snapshot()["free"]["paused"] == 0
    print("snapshot", reg.snapshot())

    # Preemption (policy iii is stock vLLM with --scheduling-policy priority + gateway priority = task start):
    # two tasks fill a 15-block pool exactly; at the first decode step one must go. The victim is the
    # younger task (larger priority value), and its freed, cached prompt blocks land in the PAUSED tier
    # (its task is live and will be re-admitted), not at the plain LRU tail.
    sch = make_scheduler(16)
    q = sch.kv_cache_manager.block_pool.free_block_queue
    old = req([11 + i % 40 for i in range(7 * BS)], {"dbkv_task": "old", "dbkv_task_start": 1.0}, prio=1000)
    young = req([200 + i % 40 for i in range(7 * BS)], {"dbkv_task": "young", "dbkv_task_start": 2.0}, prio=2000)
    sch.add_request(young)
    sch.add_request(old)
    preempted = []
    for step in range(4):
        out = sch.schedule()
        ids = list(out.num_scheduled_tokens)
        preempted += [r for r in (old, young) if r.status == RequestStatus.PREEMPTED and r not in preempted]
        if not ids:
            break
        mro = ModelRunnerOutput(req_ids=ids, req_id_to_index={r: i for i, r in enumerate(ids)},
                                sampled_token_ids=[[5] for _ in ids])
        sch.update_from_output(out, mro)
        if preempted:
            break
    print("preempted:", [r.request_id for r in preempted], "num_preemptions:",
          old.num_preemptions, young.num_preemptions, q.snapshot())
    assert preempted == [young] and old.num_preemptions == 0
    assert q.snapshot()["free"]["paused"] == 7 and reg.is_live("young")
    print("SCHED OK")


if __name__ == "__main__":
    main()
