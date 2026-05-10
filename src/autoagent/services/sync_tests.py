from __future__ import annotations

from fastapi import HTTPException

from autoagent.api._deps import get_scheduler
from autoagent.models.api import Sample, SampleResult
from autoagent.storage.samples import list_samples_for_batch


async def execute_sync_sample(sample: Sample) -> SampleResult:
    scheduler = get_scheduler()
    batch_id = await scheduler.submit(
        name=f"sync-{sample.id}",
        mode=sample.mode,
        concurrency=1,
        samples=[sample],
    )
    wait_timeout = sample.timeout_sec or (180 if sample.mode == "gui_android" else 600)
    await scheduler.wait_done(batch_id, timeout_sec=wait_timeout + 30)
    results = await list_samples_for_batch(batch_id)
    if not results:
        raise HTTPException(status_code=500, detail="no result recorded")
    return results[0]
