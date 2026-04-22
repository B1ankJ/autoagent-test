from __future__ import annotations

from typing import Any

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample


class WebExecutor(Executor):
    """Playwright-backed executor for `mode=gui_pc_web`.

    Filled in by Task 8. This skeleton exists so the scheduler factory can
    dispatch web samples and integration plumbing can be wired up.
    """

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        raise NotImplementedError("WebExecutor.execute is filled in by Task 8")
