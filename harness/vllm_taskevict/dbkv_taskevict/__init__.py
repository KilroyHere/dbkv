"""dbkv option E: task-aware KV eviction for vLLM 0.33 V1, as a general plugin (PLAN 2j, Phase 2 step E).

Entry point group "vllm.general_plugins" -> register(). vLLM calls it in every process (API server,
engine core, workers); it does nothing unless DBKV_TASKEVICT=1. Design: engine/E_task_eviction.md.

Env vars (read in the engine-core process):
  DBKV_TASKEVICT=1              switch on (anything else: the plugin is inert, vLLM is stock)
  DBKV_TASKEVICT_MODE=full      full | ended_only | paused_only | tag_only (ablations; tag_only = all hooks,
                                no reordering, for an overhead control)
  DBKV_TASKEVICT_TTL=300        s with nothing in flight before a live task's blocks fall back to plain LRU
                                (0 = never)
  DBKV_TASKEVICT_HOST/PORT      task_end listener, default 127.0.0.1:8899 (PORT=0: no listener, in-band only)
  DBKV_TASKEVICT_LOG=path       JSONL stats line every DBKV_TASKEVICT_LOG_EVERY s (default 10)
Requests are tagged by the gateway (--taskevict) with vllm_xargs {"dbkv_task": id, "dbkv_task_start": s}.
"""
import logging, os

log = logging.getLogger("dbkv_taskevict")

REGISTRY = None
CONFIG = None


def register():
    global REGISTRY, CONFIG
    if os.environ.get("DBKV_TASKEVICT", "") != "1":
        return
    if REGISTRY is not None:
        return
    from .patch import config_from_env, install
    from .registry import TaskRegistry
    CONFIG = config_from_env()
    REGISTRY = TaskRegistry(ttl=CONFIG["ttl"], log_path=CONFIG["log"], log_every=CONFIG["log_every"])
    if install(REGISTRY, CONFIG):
        log.info("dbkv_taskevict: installed (%s)", CONFIG)
