from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from autoagent.api._deps import get_scheduler
from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.loaders.csv_loader import load_csv
from autoagent.loaders.json_loader import load_json
from autoagent.loaders.jsonl_loader import load_jsonl
from autoagent.models.api import (
    BatchCreatedResponse, BatchCreateJSON, BatchDetail, BatchSummary, Mode,
)
from autoagent.storage.batches import get_batch, list_batches
from autoagent.storage.samples import list_samples_for_batch

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_user)])


def _parse_file(filename: str, text: str):
    ext = Path(filename).suffix.lower()
    if ext == ".jsonl":
        return load_jsonl(text)
    if ext == ".json":
        return load_json(text)
    if ext == ".csv":
        return load_csv(text)
    raise HTTPException(status_code=400, detail=f"unsupported extension {ext}")


def _apply_default_profile(samples, default_profile: str | None):
    if default_profile is None:
        return
    for s in samples:
        if not s.target_profile:
            s.target_profile = default_profile


@router.post("", response_model=BatchCreatedResponse, status_code=201)
async def create_batch_json(body: BatchCreateJSON) -> BatchCreatedResponse:
    _apply_default_profile(body.samples, body.target_profile_default)
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=body.name, mode=body.mode, concurrency=body.concurrency, samples=body.samples,
        target_profile_default=body.target_profile_default,
    )
    return BatchCreatedResponse(batch_id=batch_id)


@router.post("/upload", response_model=BatchCreatedResponse, status_code=201)
async def create_batch_file(
    name: str = Form(...),
    mode: Mode = Form(...),
    concurrency: int = Form(1),
    target_profile_default: str | None = Form(None),
    file: UploadFile = File(...),
) -> BatchCreatedResponse:
    try:
        text = (await file.read()).decode("utf-8")
        samples = _parse_file(file.filename or "batch.jsonl", text)
    except (UnicodeDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _apply_default_profile(samples, target_profile_default)
    # Validate all modes match
    for s in samples:
        if s.mode != mode:
            raise HTTPException(status_code=400, detail=f"sample {s.id} mode={s.mode} != batch mode={mode}")
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=name, mode=mode, concurrency=concurrency, samples=samples,
        target_profile_default=target_profile_default,
    )
    return BatchCreatedResponse(batch_id=batch_id)


@router.get("", response_model=list[BatchSummary])
async def list_all(limit: int = 50, offset: int = 0) -> list[BatchSummary]:
    rows = await list_batches(limit=limit, offset=offset)
    return [
        BatchSummary(
            batch_id=r.id, name=r.name, mode=r.mode, status=r.status,
            total=r.total, done=r.done, failed=r.failed,
            avg_duration_ms=r.avg_duration_ms, total_duration_ms=r.total_duration_ms,
            started_at=r.started_at, ended_at=r.ended_at,
        ) for r in rows
    ]


@router.get("/{batch_id}", response_model=BatchDetail)
async def get_one(batch_id: str) -> BatchDetail:
    b = await get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    samples = await list_samples_for_batch(batch_id)
    return BatchDetail(
        batch_id=b.id, name=b.name, mode=b.mode, status=b.status,
        total=b.total, done=b.done, failed=b.failed,
        avg_duration_ms=b.avg_duration_ms, total_duration_ms=b.total_duration_ms,
        started_at=b.started_at, ended_at=b.ended_at,
        samples=samples,
    )


@router.get("/{batch_id}/results")
async def download_results(batch_id: str) -> FileResponse:
    b = await get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    path = get_settings().data_root / "results" / f"{batch_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="results file not found")
    return FileResponse(path, media_type="application/x-ndjson", filename=f"{batch_id}.jsonl")


@router.post("/{batch_id}/cancel", status_code=202)
async def cancel(batch_id: str) -> dict:
    sch = get_scheduler()
    ok = await sch.cancel(batch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="batch not found or already finished")
    return {"batch_id": batch_id, "status": "cancelling"}
