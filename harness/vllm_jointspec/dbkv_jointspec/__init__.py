"""dbkv option C: joint speculation and prefill budget (PLAN 2j, Phase 2 C).

vLLM general plugin (entry point group `vllm.general_plugins`). `register()`
is a no-op unless DBKV_JOINTSPEC=1. When on, it wraps
`SchedulerConfig.get_scheduler_cls` so that whatever scheduler class vLLM
picks (Scheduler, or AsyncScheduler) is returned as a JointSpec subclass.
The installed vLLM files are not modified. See engine/C_joint_spec.md.
"""

import logging

from .policy import AcceptanceTracker, Allocation, Knobs, allocate  # noqa: F401

logger = logging.getLogger("vllm.dbkv_jointspec")  # child of vllm: uses its handler

_MARK = "_dbkv_jointspec_wrapped"


def register() -> None:
    """vLLM calls this in every process (API server, engine core, workers).
    Must be idempotent and cheap."""
    if not Knobs.from_env().enabled:
        return
    from vllm.config.scheduler import SchedulerConfig

    orig = SchedulerConfig.get_scheduler_cls
    if getattr(orig, _MARK, False):
        return

    from .scheduler import wrap_scheduler_cls

    def get_scheduler_cls(self):
        return wrap_scheduler_cls(orig(self))

    setattr(get_scheduler_cls, _MARK, True)
    get_scheduler_cls.__wrapped__ = orig
    SchedulerConfig.get_scheduler_cls = get_scheduler_cls
    logger.info("dbkv_jointspec: SchedulerConfig.get_scheduler_cls wrapped")


def unregister() -> None:
    """Undo `register()` (tests)."""
    from vllm.config.scheduler import SchedulerConfig

    cur = SchedulerConfig.get_scheduler_cls
    if getattr(cur, _MARK, False):
        SchedulerConfig.get_scheduler_cls = cur.__wrapped__
