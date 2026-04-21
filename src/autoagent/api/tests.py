from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException

from autoagent.api._deps import get_scheduler
from autoagent.auth.deps import require_user
from autoagent.models.api import AsyncTestResponse, Sample, SampleResult
from autoagent.storage.samples import list_samples_for_batch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(require_user)])


@router.post("/sync", response_model=SampleResult)
async def run_sync(sample: Sample) -> SampleResult:
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=f"sync-{sample.id}", mode=sample.mode, concurrency=1, samples=[sample],
    )
    await sch.wait_done(batch_id, timeout_sec=(sample.timeout_sec or 600) + 30)
    results = await list_samples_for_batch(batch_id)
    if not results:
        raise HTTPException(status_code=500, detail="no result recorded")
    return results[0]


@router.post("", response_model=AsyncTestResponse, status_code=202)
async def run_async(sample: Sample) -> AsyncTestResponse:
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=f"async-{sample.id}", mode=sample.mode, concurrency=1, samples=[sample],
    )
    return AsyncTestResponse(task_id=batch_id)


@router.get("/{task_id}", response_model=SampleResult)
async def get_async_result(task_id: str) -> SampleResult:
    results = await list_samples_for_batch(task_id)
    if not results:
        raise HTTPException(status_code=404, detail="task not found or no result yet")
    return results[0]
