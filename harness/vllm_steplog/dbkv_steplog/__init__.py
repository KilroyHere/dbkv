"""Per-step vLLM engine log for dbkv (PLAN 2j, Phase 1 instrumentation, kept for every later phase).

A vLLM stat-logger plugin (entry point group "vllm.stat_logger_plugins"). It is inert unless the env var
DBKV_STEPLOG names a JSONL file; then every record() call (one per engine step's outputs) appends one line:
  t, step, running, waiting, kv_usage,
  ctx_reqs / ctx_tokens (prefill), gen_reqs / gen_tokens (decode), step_ms   <- needs --enable-logging-iteration-details
  pc_queries / pc_hits (prefix cache, this step), pc_preempted_queries / pc_preempted_hits, pc_reset,
  spec_drafts / spec_draft_tokens / spec_accepted                          <- with speculative decoding
  preempted (requests preempted this step), gen_out_tokens (frontend count), n_finished,
  evict_n / evict_idle_s_p50 / evict_lifetime_s_p50 / evict_reuse_gaps     <- needs --kv-cache-metrics (sampled)
Install (no download; our own code): pip install --no-deps --no-build-isolation -e harness/vllm_steplog
"""
import json, os, time

from vllm.v1.metrics.loggers import StatLoggerBase


def _p50(v):
    v = sorted(v)
    return round(v[len(v) // 2], 3) if v else None


class StepLogger(StatLoggerBase):
    def __init__(self, vllm_config, engine_index: int = 0):
        self.path = os.environ.get("DBKV_STEPLOG", "")
        self.f = open(self.path, "a", buffering=1) if self.path else None
        self.engine_index = engine_index
        self.n = 0

    def record(self, scheduler_stats, iteration_stats, mm_cache_stats=None, engine_idx: int = 0):
        if self.f is None:
            return
        r = dict(t=round(time.time(), 4), e=engine_idx)
        s = scheduler_stats
        if s is not None:
            r.update(step=s.step_counter, running=s.num_running_reqs, waiting=s.num_waiting_reqs,
                     kv_usage=round(s.kv_cache_usage, 5))
            d = s.iteration_details
            if d is not None:
                r.update(it=d.iteration_index, ctx_reqs=d.num_ctx_requests, ctx_tokens=d.num_ctx_tokens,
                         gen_reqs=d.num_generation_requests, gen_tokens=d.num_generation_tokens,
                         step_ms=round(d.elapsed_ms, 3), dummy=d.is_dummy)
            pc = s.prefix_cache_stats
            if pc is not None:
                r.update(pc_reqs=pc.requests, pc_queries=pc.queries, pc_hits=pc.hits,
                         pc_preempted_reqs=pc.preempted_requests, pc_preempted_queries=pc.preempted_queries,
                         pc_preempted_hits=pc.preempted_hits, pc_reset=pc.reset)
            sd = s.spec_decoding_stats
            if sd is not None:
                r.update(spec_drafts=sd.num_drafts, spec_draft_tokens=sd.num_draft_tokens,
                         spec_accepted=sd.num_accepted_tokens)
            ev = s.kv_cache_eviction_events or []
            if ev:
                r.update(evict_n=len(ev), evict_idle_s_p50=_p50([e.idle_seconds for e in ev]),
                         evict_lifetime_s_p50=_p50([e.lifetime_seconds for e in ev]),
                         evict_reused=sum(1 for e in ev if e.reuse_gaps_seconds))
        it = iteration_stats
        if it is not None:
            r.update(gen_out_tokens=it.num_generation_tokens, prompt_tokens=it.num_prompt_tokens,
                     preempted=it.num_preempted_reqs, n_finished=len(it.finished_requests))
        self.f.write(json.dumps(r) + "\n")
        self.n += 1

    def log_engine_initialized(self):
        if self.f is not None:
            self.f.write(json.dumps(dict(t=round(time.time(), 4), ev="engine_initialized",
                                         engine=self.engine_index)) + "\n")

    def log(self):
        pass
