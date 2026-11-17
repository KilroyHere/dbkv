"""CPU test of the patched vLLM 0.33 scheduler (no GPU, no model weights).

Builds a real `Scheduler` the way vLLM's own tests/v1/core/utils.py does
(model config from the local Qwen3-8B config.json, ngram speculative config
so no drafter is needed, a fake KV cache config), injects drafts with
`update_draft_token_ids`, and checks the token split of one step against the
stock scheduler in the same state.

Run on a CPU node (imports torch + vLLM):
  srun -A m4999 -C cpu -q shared_interactive -c 8 -t 00:20:00 \
    $DBKV_ENV/bin/python -m unittest discover -s harness/vllm_jointspec/tests -v
"""

import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

K = 24  # num_speculative_tokens (suffix default tree depth)
BLOCK = 16


def _model_path():
    hf = os.environ.get("HF_HOME", "/pscratch/sd/a/ap2568/huggingface")
    snaps = sorted(glob.glob(os.path.join(hf, "hub/models--Qwen--Qwen3-8B/snapshots/*")))
    if not snaps:
        raise unittest.SkipTest("Qwen3-8B config not in HF cache")
    return snaps[-1]


def make_scheduler(max_num_batched_tokens=1024, max_num_seqs=128, num_blocks=4096):
    import torch
    from vllm.config import (CacheConfig, ModelConfig, SchedulerConfig,
                             SpeculativeConfig, VllmConfig)
    from vllm.v1.kv_cache_interface import (FullAttentionSpec, KVCacheConfig,
                                            KVCacheGroupSpec)
    from vllm.v1.structured_output import StructuredOutputManager

    model_config = ModelConfig(
        model=_model_path(), trust_remote_code=False, dtype="float16", seed=42,
        skip_tokenizer_init=True, max_model_len=8192,
    )
    scheduler_config = SchedulerConfig(
        max_num_seqs=max_num_seqs,
        max_num_batched_tokens=max_num_batched_tokens,
        max_model_len=8192,
        long_prefill_token_threshold=0,
        enable_chunked_prefill=True,
        is_encoder_decoder=False,
        async_scheduling=False,
    )
    cache_config = CacheConfig(block_size=BLOCK, gpu_memory_utilization=0.9,
                               cache_dtype="auto", enable_prefix_caching=False)
    spec = SpeculativeConfig(method="ngram", num_speculative_tokens=K,
                             prompt_lookup_max=4, prompt_lookup_min=2)
    vllm_config = VllmConfig(scheduler_config=scheduler_config, model_config=model_config,
                             cache_config=cache_config, speculative_config=spec)
    vllm_config.scheduler_config.async_scheduling = False
    kv_cache_config = KVCacheConfig(
        num_blocks=num_blocks, kv_cache_tensors=[],
        kv_cache_groups=[KVCacheGroupSpec(["layer"], FullAttentionSpec(
            block_size=BLOCK, num_kv_heads=1, head_size=1, dtype=torch.float32))],
    )
    cache_config.num_gpu_blocks = num_blocks
    cls = vllm_config.scheduler_config.get_scheduler_cls()
    return cls(vllm_config=vllm_config, kv_cache_config=kv_cache_config,
               structured_output_manager=StructuredOutputManager(vllm_config),
               block_size=BLOCK, log_stats=True)


def make_request(rid, n_prompt, max_tokens=200):
    from vllm.sampling_params import SamplingParams
    from vllm.v1.request import Request

    sp = SamplingParams(max_tokens=max_tokens, ignore_eos=True)
    return Request(request_id=rid, prompt_token_ids=[(i * 7 + hash(rid)) % 1000 + 10
                                                      for i in range(n_prompt)],
                   sampling_params=sp, pooling_params=None)


def run_output(sched, out, accepted=None):
    """Fake model step: every scheduled request samples 1 + accepted tokens."""
    from vllm.v1.outputs import ModelRunnerOutput

    accepted = accepted or {}
    rids = list(out.num_scheduled_tokens.keys())
    sampled = []
    for rid in rids:
        req = sched.requests[rid]
        # schedule() already advanced num_computed_tokens; a partial prefill
        # chunk is still short of num_tokens and samples nothing.
        if req.num_computed_tokens < req.num_tokens:
            sampled.append([])
            continue
        n_spec = len(out.scheduled_spec_decode_tokens.get(rid, []))
        a = min(accepted.get(rid, 0), n_spec)
        sampled.append([5] * (1 + a))
    mro = ModelRunnerOutput(req_ids=rids, req_id_to_index={r: i for i, r in enumerate(rids)},
                            sampled_token_ids=sampled)
    return sched.update_from_output(out, mro)


def set_drafts(sched, drafts):
    from vllm.v1.outputs import DraftTokenIds

    rids = list(drafts)
    sched.update_draft_token_ids(DraftTokenIds(rids, [drafts[r] for r in rids]))


def build_state(sched, n_dec=32, n_wait=4, wait_len=600):
    """n_dec requests decoding (prompt done, 1 token out), each with K drafts;
    n_wait new requests waiting with `wait_len`-token prompts."""
    for i in range(n_dec):
        sched.add_request(make_request(f"d{i}", 40))
    for _ in range(10):  # prefill all prompts (may take >1 step)
        run_output(sched, sched.schedule())
        if all(sched.requests[f"d{i}"].num_output_tokens >= 1 for i in range(n_dec)):
            break
    assert all(sched.requests[f"d{i}"].num_output_tokens >= 1 for i in range(n_dec))
    set_drafts(sched, {f"d{i}": [11] * K for i in range(n_dec)})
    for j in range(n_wait):
        sched.add_request(make_request(f"w{j}", wait_len))


class _Env:
    def __init__(self, **kv):
        self.kv = {k: str(v) for k, v in kv.items()}

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.kv}
        os.environ.update(self.kv)

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def split(out, sched):
    spec = {r: len(v) for r, v in out.scheduled_spec_decode_tokens.items()}
    dec = {r: n for r, n in out.num_scheduled_tokens.items() if r.startswith("d")}
    pre = sum(n for r, n in out.num_scheduled_tokens.items() if r.startswith("w"))
    return dec, spec, pre


class TestPatchedScheduler(unittest.TestCase):
    def setUp(self):
        import dbkv_jointspec
        dbkv_jointspec.unregister()

    tearDown = setUp

    def test_noop_without_env(self):
        import dbkv_jointspec
        from vllm.v1.core.sched.scheduler import Scheduler
        with _Env(DBKV_JOINTSPEC="0"):
            dbkv_jointspec.register()
            s = make_scheduler()
        self.assertIs(type(s), Scheduler)

    def test_split_vs_stock(self):
        import dbkv_jointspec
        from dbkv_jointspec.scheduler import JointSpecMixin

        B = 1024
        # Stock: 32 decodes x (1 + 24) = 800 tokens of decode+drafts, then the
        # 4 waiting prompts (2400 tokens) get the remaining 224.
        stock = make_scheduler(max_num_batched_tokens=B)
        build_state(stock)
        dec0, spec0, pre0 = split(stock.schedule(), stock)
        print(f"\nstock : decode reqs {len(dec0)}, spec {sum(spec0.values())}, prefill {pre0}")

        with _Env(DBKV_JOINTSPEC="1", DBKV_JOINTSPEC_BUDGET=512, DBKV_JOINTSPEC_THETA=0.5,
                  DBKV_JOINTSPEC_WAIT_HIT=0.0):
            dbkv_jointspec.register()
            js = make_scheduler(max_num_batched_tokens=B)
        self.assertIsInstance(js, JointSpecMixin)
        build_state(js)
        # Seed acceptance: d0..d15 accept ~0.9 per position, d16..d31 ~0.3.
        for i in range(32):
            for _ in range(20):
                js._js_tracker.observe(f"d{i}", 10, 9 if i < 16 else 0)
        out = js.schedule()
        dec, spec, pre = split(out, js)
        alloc = js._js_last
        print(f"joint : decode reqs {len(dec)}, spec {sum(spec.values())} "
              f"(hi {alloc.spec_hi}, lo {alloc.spec_lo}), prefill {pre}, "
              f"total {out.total_num_scheduled_tokens} / budget 512")
        print("        spec per req (high-p d0..d15):", [spec.get(f'd{i}', 0) for i in range(16)])
        print("        spec per req (low-p d16..d31):", [spec.get(f'd{i}', 0) for i in range(16, 32)])

        self.assertEqual(len(dec), 32)                     # every decode served
        self.assertLessEqual(out.total_num_scheduled_tokens, 512)  # policy budget
        hi = sum(spec.get(f"d{i}", 0) for i in range(16))
        lo = sum(spec.get(f"d{i}", 0) for i in range(16, 32))
        self.assertGreater(hi, lo)                         # by acceptance
        self.assertEqual(sum(spec.values()), alloc.n_spec)  # scheduler obeyed trims
        self.assertEqual(pre, alloc.prefill)               # prefill got its share
        self.assertGreater(pre, 0)
        for r, n in dec.items():
            self.assertEqual(n, 1 + spec.get(r, 0))

        # Acceptance bookkeeping through update_from_output.
        before = js._js_tracker.p("d0")
        run_output(js, out, accepted={f"d{i}": 0 for i in range(32)})
        self.assertLess(js._js_tracker.p("d0"), before)

    def test_decode_floor_when_drafts_exceed_budget(self):
        """64 decodes x (1 + 24) = 1600 > 1024: stock serves the first ~40
        requests with full drafts and starves the rest for this step; joint
        (theta 0, no extra budget cap) serves all 64, trimming drafts."""
        import dbkv_jointspec
        stock = make_scheduler(max_num_batched_tokens=1024)
        build_state(stock, n_dec=64, n_wait=0)
        dec0, spec0, _ = split(stock.schedule(), stock)
        with _Env(DBKV_JOINTSPEC="1", DBKV_JOINTSPEC_THETA=0.0):
            dbkv_jointspec.register()
            js = make_scheduler(max_num_batched_tokens=1024)
        build_state(js, n_dec=64, n_wait=0)
        out = js.schedule()
        dec, spec, _ = split(out, js)
        print(f"\nstock : decode reqs served {len(dec0)}/64, spec {sum(spec0.values())}")
        print(f"joint : decode reqs served {len(dec)}/64, spec {sum(spec.values())}, "
              f"total {out.total_num_scheduled_tokens}")
        self.assertLess(len(dec0), 64)
        self.assertEqual(len(dec), 64)
        self.assertLessEqual(out.total_num_scheduled_tokens, 1024)
        self.assertEqual(out.total_num_scheduled_tokens, 1024)  # budget fully used

    def test_theta_zero_matches_stock_when_uncontended(self):
        import dbkv_jointspec
        with _Env(DBKV_JOINTSPEC="1", DBKV_JOINTSPEC_THETA=0.0):
            dbkv_jointspec.register()
            js = make_scheduler(max_num_batched_tokens=4096)
        stock_cls = type(js).__mro__[2]
        build_state(js, n_wait=1, wait_len=200)
        out = js.schedule()
        dec, spec, pre = split(out, js)
        self.assertEqual(sum(spec.values()), 32 * K)  # nothing trimmed
        self.assertEqual(pre, 200)
        self.assertEqual(stock_cls.__name__, "Scheduler")


if __name__ == "__main__":
    unittest.main()
