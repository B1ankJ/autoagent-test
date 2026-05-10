from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import HTTPException

from autoagent.models.api import Sample, SampleResult


class SyncSampleScheduler(Protocol):
    async def submit(self, **kwargs) -> str: ...

    async def wait_done(self, batch_id: str, timeout_sec: float | None = None) -> None: ...


async def execute_sync_sample(
    sample: Sample,
    *,
    get_scheduler_fn: Callable[[], SyncSampleScheduler],
    list_samples_for_batch_fn: Callable[[str], Awaitable[list[SampleResult]]],
) -> SampleResult:
    scheduler = get_scheduler_fn()
    batch_id = await scheduler.submit(
        name=f"sync-{sample.id}",
        mode=sample.mode,
        concurrency=1,
        samples=[sample],
    )
    wait_timeout = sample.timeout_sec or (180 if sample.mode == "gui_android" else 600)
    # sample.timeout_sec is the per-sample timeout; we wait slightly longer
    # to absorb executor startup/teardown, including GUI driver startup time.
    await scheduler.wait_done(batch_id, timeout_sec=wait_timeout + 30)
    results = await list_samples_for_batch_fn(batch_id)
    if not results:
        raise HTTPException(status_code=500, detail="no result recorded")
    return results[0]
