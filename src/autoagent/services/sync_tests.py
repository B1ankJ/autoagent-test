from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from autoagent.api._deps import get_scheduler
from autoagent.models.api import Sample, SampleResult
from autoagent.storage.samples import list_samples_for_batch


async def execute_sync_sample(
    sample: Sample,
    *,
    get_scheduler_fn: Callable[[], object] = get_scheduler,
    list_samples_for_batch_fn: Callable[[str], Awaitable[list[SampleResult]]] = list_samples_for_batch,
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
