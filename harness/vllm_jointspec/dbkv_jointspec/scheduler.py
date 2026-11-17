"""Option C scheduler: a thin wrapper around vLLM 0.33's V1 Scheduler.

It does not change `Scheduler.schedule()` itself. Before calling it, it
  1. builds the step's demand from `self.running` / `self.waiting`,
  2. calls the pure policy (`policy.allocate`),
  3. trims each running decode request's `spec_token_ids` to its allocation
     (the stock scheduler already slices drafts the same way when the budget
     runs out: scheduler.py ~L1010-1021),
  4. optionally lowers `max_num_scheduled_tokens` to the policy budget for
     this one call, and stably moves decode requests ahead of running prefill
     chunks.
After the model step, `update_from_output` feeds per-request accepted /
drafted counts into the acceptance tracker before the stock bookkeeping runs.

Only active in synchronous scheduling with a speculative method configured
(suffix decoding forces both in vLLM 0.33). Otherwise it is a pass-through.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time

from .policy import AcceptanceTracker, Knobs, allocate

logger = logging.getLogger("vllm.dbkv_jointspec")  # child of vllm: uses its handler

_PRUNE_EVERY = 256


class JointSpecMixin:
    """Mix in before vLLM's Scheduler (MRO: JointSpecMixin -> Scheduler)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._js_knobs = Knobs.from_env()
        k = self._js_knobs
        self._js_tracker = AcceptanceTracker(k.ewma, k.prior_weight, k.p_init)
        self._js_step = 0
        self._js_log = None
        self._js_last = None  # last Allocation, for tests / logging
        is_async = bool(getattr(self.scheduler_config, "async_scheduling", False))
        self._js_active = self.num_spec_tokens > 0 and not is_async
        if self.num_spec_tokens > 0 and is_async:
            logger.warning(
                "dbkv_jointspec: async scheduling is on; the joint spec/prefill "
                "policy only runs with synchronous scheduling. Pass-through."
            )
        logger.info(
            "dbkv_jointspec: %s (num_spec_tokens=%d, knobs=%s)",
            "ACTIVE" if self._js_active else "inactive (no spec decode)",
            self.num_spec_tokens,
            k,
        )

    # ------------------------------------------------------------------ plan
    def _js_budget(self) -> int:
        b = self.max_num_scheduled_tokens
        if self._js_knobs.budget > 0:
            b = min(b, self._js_knobs.budget)
        return b

    def _js_demand(self):
        """(n_decode, drafts, prefill_demand, n_drafts_available)."""
        n_decode = 0
        drafts = []
        prefill = 0
        n_avail = 0
        tr = self._js_tracker
        for r in self.running:
            remaining = r.num_tokens - r.num_computed_tokens
            if remaining <= 1:
                n_decode += 1
                if r.spec_token_ids:
                    n = len(r.spec_token_ids)
                    n_avail += n
                    drafts.append((r.request_id, n, tr.p(r.request_id)))
            else:
                prefill += remaining
        # Waiting prompts can only be admitted while there are free seq slots.
        budget = self._js_budget()
        if len(self.running) < self.max_num_running_reqs:
            miss = max(0.0, 1.0 - self._js_knobs.wait_hit)
            for r in self.waiting:
                if prefill >= budget:
                    break
                prefill += int(math.ceil((r.num_tokens - r.num_computed_tokens) * miss))
        return n_decode, drafts, prefill, n_avail

    def _js_apply(self):
        k = self._js_knobs
        n_decode, drafts, prefill, n_avail = self._js_demand()
        alloc = allocate(
            self._js_budget(),
            n_decode,
            drafts,
            prefill,
            theta=k.theta,
            min_value=k.min_value,
            fill_leftover=k.fill_leftover,
        )
        if drafts:
            by_id = self.requests
            for rid, keep in alloc.spec.items():
                req = by_id.get(rid)
                if req is not None and len(req.spec_token_ids) > keep:
                    req.spec_token_ids = list(req.spec_token_ids[:keep])
        if k.decode_first and len(self.running) > 1:
            dec, pre = [], []
            for r in self.running:
                (dec if r.num_tokens - r.num_computed_tokens <= 1 else pre).append(r)
            if pre and dec:
                self.running[:] = dec + pre
        return alloc, prefill, n_avail

    # -------------------------------------------------------------- overrides
    def schedule(self, *args, **kwargs):
        if not self._js_active:
            return super().schedule(*args, **kwargs)
        self._js_step += 1
        alloc, prefill_demand, n_avail = self._js_apply()
        self._js_last = alloc
        orig = self.max_num_scheduled_tokens
        self.max_num_scheduled_tokens = self._js_budget()
        try:
            out = super().schedule(*args, **kwargs)
        finally:
            self.max_num_scheduled_tokens = orig
        if self._js_step % _PRUNE_EVERY == 0:
            self._js_tracker.forget(self.requests.keys())
        if self._js_knobs.log_path and self._js_step % self._js_knobs.log_every == 0:
            self._js_write_log(alloc, prefill_demand, n_avail, out)
        return out

    def update_from_output(self, scheduler_output, model_runner_output):
        if self._js_active:
            try:
                self._js_observe(scheduler_output, model_runner_output)
            except Exception:  # never break the engine over bookkeeping
                logger.exception("dbkv_jointspec: acceptance bookkeeping failed")
        return super().update_from_output(scheduler_output, model_runner_output)

    # ------------------------------------------------------------- tracking
    def _js_observe(self, scheduler_output, model_runner_output):
        sched_spec = scheduler_output.scheduled_spec_decode_tokens
        sampled = model_runner_output.sampled_token_ids
        if not sched_spec or not sampled:
            return
        idx = model_runner_output.req_id_to_index
        invalid = scheduler_output.num_invalid_spec_tokens or {}
        ns = self.num_sampled_tokens_per_step
        for rid, toks in sched_spec.items():
            i = idx.get(rid)
            if i is None or i >= len(sampled):
                continue
            gen = sampled[i]
            if not gen:
                continue
            n_draft = len(toks) - invalid.get(rid, 0)
            n_acc = max(len(gen) - ns, 0)
            self._js_tracker.observe(rid, n_draft, n_acc)

    # -------------------------------------------------------------- logging
    def _js_write_log(self, alloc, prefill_demand, n_avail, out):
        try:
            if self._js_log is None:
                path = self._js_knobs.log_path.replace("{pid}", str(os.getpid()))
                self._js_log = open(path, "a", buffering=1 << 16)
            n_spec_sched = sum(len(v) for v in out.scheduled_spec_decode_tokens.values())
            rec = {
                "t": round(time.time(), 4),
                "step": self._js_step,
                "budget": alloc.budget,
                "n_decode": alloc.n_decode,
                "drafts_avail": n_avail,
                "spec_alloc": alloc.n_spec,
                "spec_hi": alloc.spec_hi,
                "spec_lo": alloc.spec_lo,
                "prefill_demand": prefill_demand,
                "prefill_alloc": alloc.prefill,
                "p_global": round(self._js_tracker.global_p(), 4),
                "sched_total": out.total_num_scheduled_tokens,
                "sched_spec": n_spec_sched,
                "n_running": len(self.running),
                "n_waiting": len(self.waiting),
            }
            self._js_log.write(json.dumps(rec) + "\n")
        except Exception:
            logger.exception("dbkv_jointspec: log write failed; logging off")
            self._js_knobs = _replace_log(self._js_knobs)


def _replace_log(k: Knobs) -> Knobs:
    from dataclasses import replace

    return replace(k, log_path="")


_WRAPPED: dict = {}


def wrap_scheduler_cls(cls):
    """Return a JointSpec subclass of `cls` (cached; idempotent)."""
    if isinstance(cls, type) and issubclass(cls, JointSpecMixin):
        return cls
    w = _WRAPPED.get(cls)
    if w is None:
        w = type("JointSpec" + cls.__name__, (JointSpecMixin, cls), {})
        w.__module__ = __name__
        _WRAPPED[cls] = w
    return w


def __getattr__(name):
    # `--scheduler-cls dbkv_jointspec.scheduler.JointSpecScheduler` works too
    # (no plugin, no env switch needed); resolved lazily so importing this
    # module does not import vLLM.
    if name == "JointSpecScheduler":
        from vllm.v1.core.sched.scheduler import Scheduler

        return wrap_scheduler_cls(Scheduler)
    raise AttributeError(name)
