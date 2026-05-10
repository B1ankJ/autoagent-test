from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from autoagent.api._deps import get_scheduler
from autoagent.auth.deps import require_user
from autoagent.models.api import AsyncTestResponse, Sample, SampleResult
from autoagent.services.sync_tests import execute_sync_sample
from autoagent.storage.samples import list_samples_for_batch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(require_user)])


async def execute_sync_test(sample: Sample) -> SampleResult:
    return await execute_sync_sample(
        sample,
        get_scheduler_fn=get_scheduler,
        list_samples_for_batch_fn=list_samples_for_batch,
    )


@router.post("/sync", response_model=SampleResult)
async def run_sync(sample: Sample) -> SampleResult:
    return await execute_sync_test(sample)


@router.post("", response_model=AsyncTestResponse, status_code=202)
async def run_async(sample: Sample) -> AsyncTestResponse:
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=f"async-{sample.id}",
        mode=sample.mode,
        concurrency=1,
        samples=[sample],
    )
    return AsyncTestResponse(task_id=batch_id)


@router.get("/{task_id}", response_model=SampleResult)
async def get_async_result(task_id: str) -> SampleResult:
    results = await list_samples_for_batch(task_id)
    if not results:
        raise HTTPException(status_code=404, detail="task not found or no result yet")
    return results[0]
