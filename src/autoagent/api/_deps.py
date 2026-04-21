from __future__ import annotations

from typing import Any

from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.base import Executor
from autoagent.profiles.registry import load_profile
from autoagent.scheduler.batch_scheduler import BatchScheduler

_scheduler: BatchScheduler | None = None


def _build_executor(mode: str) -> Executor:
    if mode == "api":
        return ApiExecutor()
    raise ValueError(f"mode {mode} not supported in this build (see later plans for web/android)")


def _lookup_profile(name: str) -> Any:
    p = load_profile(name)
    if p is None:
        raise LookupError(f"profile {name!r} not found")
    return p


def get_scheduler() -> BatchScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BatchScheduler(executor_factory=_build_executor, profile_lookup=_lookup_profile)
    return _scheduler


def reset_scheduler_for_tests() -> None:
    global _scheduler
    _scheduler = None
