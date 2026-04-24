from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import OperationalError
from sse_starlette.sse import EventSourceResponse

from autoagent.api._deps import get_scheduler
from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.events.bus import get_event_bus
from autoagent.loaders.csv_loader import load_csv
from autoagent.loaders.json_loader import load_json
from autoagent.loaders.jsonl_loader import load_jsonl
from autoagent.models.api import (
    BatchCreatedResponse,
    BatchCreateJSON,
    BatchDetail,
    BatchSummary,
    Mode,
    ScreenshotInfo,
)
from autoagent.storage.batches import get_batch, list_batches
from autoagent.storage.samples import list_samples_for_batch

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_user)])
_SCREENSHOT_RE = re.compile(r"^[a-z0-9_]+\.png$")


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


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


async def _screenshot_meta_map(batch_id: str, sample_id: str) -> tuple[dict[str, dict], dict[str, int]]:
    try:
        samples = await list_samples_for_batch(batch_id)
    except OperationalError:
        return {}, {}
    for sample in samples:
        if sample.id != sample_id:
            continue
        shots = sample.metadata.get("screenshots")
        if isinstance(shots, list):
            meta_map = {
                str(item.get("name")): item
                for item in shots
                if isinstance(item, dict) and item.get("name")
            }
            order_map = {
                str(item.get("name")): index
                for index, item in enumerate(shots)
                if isinstance(item, dict) and item.get("name")
            }
            return meta_map, order_map
    return {}, {}


async def _sample_logs_dir(batch_id: str, sample_id: str) -> Path | None:
    try:
        samples = await list_samples_for_batch(batch_id)
    except OperationalError:
        return None
    for sample in samples:
        if sample.id != sample_id or not sample.logs_dir:
            continue
        return Path(sample.logs_dir).resolve()
    return None


@router.post("", response_model=BatchCreatedResponse, status_code=201)
async def create_batch_json(body: BatchCreateJSON) -> BatchCreatedResponse:
    _apply_default_profile(body.samples, body.target_profile_default)
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=body.name,
        mode=body.mode,
        concurrency=body.concurrency,
        samples=body.samples,
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    _apply_default_profile(samples, target_profile_default)
    # Validate all modes match
    for s in samples:
        if s.mode != mode:
            raise HTTPException(
                status_code=400, detail=f"sample {s.id} mode={s.mode} != batch mode={mode}"
            )
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=name,
        mode=mode,
        concurrency=concurrency,
        samples=samples,
        target_profile_default=target_profile_default,
    )
    return BatchCreatedResponse(batch_id=batch_id)


@router.get("", response_model=list[BatchSummary])
async def list_all(limit: int = 50, offset: int = 0) -> list[BatchSummary]:
    rows = await list_batches(limit=limit, offset=offset)
    return [
        BatchSummary(
            batch_id=r.id,
            name=r.name,
            mode=r.mode,
            status=r.status,
            total=r.total,
            done=r.done,
            failed=r.failed,
            avg_duration_ms=r.avg_duration_ms,
            total_duration_ms=r.total_duration_ms,
            started_at=r.started_at,
            ended_at=r.ended_at,
        )
        for r in rows
    ]


@router.get("/{batch_id}", response_model=BatchDetail)
async def get_one(batch_id: str) -> BatchDetail:
    b = await get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    samples = await list_samples_for_batch(batch_id)
    return BatchDetail(
        batch_id=b.id,
        name=b.name,
        mode=b.mode,
        status=b.status,
        concurrency=b.concurrency,
        target_profile_default=b.target_profile_default,
        total=b.total,
        done=b.done,
        failed=b.failed,
        avg_duration_ms=b.avg_duration_ms,
        total_duration_ms=b.total_duration_ms,
        started_at=b.started_at,
        ended_at=b.ended_at,
        samples=samples,
        seq=get_event_bus().last_seq(batch_id),
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


@router.get("/{batch_id}/events")
async def stream_batch_events(batch_id: str) -> EventSourceResponse:
    bus = get_event_bus()

    async def generator():
        async for event in bus.subscribe(batch_id):
            yield {
                "id": str(event.seq),
                "event": event.kind,
                "data": _json_dumps(
                    {
                        "seq": event.seq,
                        "kind": event.kind,
                        "payload": event.payload,
                        "ts": event.ts,
                    }
                ),
            }
            if event.kind == "batch_done":
                break

    return EventSourceResponse(generator())


@router.get("/{batch_id}/samples/{sample_id}/screenshots", response_model=list[ScreenshotInfo])
async def list_screenshots(batch_id: str, sample_id: str) -> list[ScreenshotInfo]:
    settings = get_settings()
    sample_dir = await _sample_logs_dir(batch_id, sample_id)
    if sample_dir is None:
        sample_dir = (settings.logs_root / batch_id / sample_id).resolve()
    if not sample_dir.is_dir():
        return []

    meta_map, order_map = await _screenshot_meta_map(batch_id, sample_id)
    out: list[ScreenshotInfo] = []
    entries = sorted(
        sample_dir.iterdir(),
        key=lambda entry: (order_map.get(entry.name, 10_000), entry.name),
    )
    for entry in entries:
        if not entry.is_file() or not _SCREENSHOT_RE.match(entry.name):
            continue
        meta = meta_map.get(entry.name, {})
        fallback_label = entry.stem.split("_", 1)[1] if "_" in entry.stem else entry.stem
        label = str(meta.get("label") or fallback_label)
        taken = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        out.append(
            ScreenshotInfo(
                name=entry.name,
                label=label,
                taken_at=taken,
                is_sensitive=bool(meta.get("is_sensitive")) if meta else None,
            )
        )
    return out


@router.get("/{batch_id}/samples/{sample_id}/actions.jsonl")
async def download_actions(batch_id: str, sample_id: str) -> FileResponse:
    root = get_settings().logs_root.resolve()
    sample_dir = await _sample_logs_dir(batch_id, sample_id)
    if sample_dir is None:
        sample_dir = (root / batch_id / sample_id).resolve()
    target = (sample_dir / "actions.jsonl").resolve()
    try:
        target.relative_to(sample_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path traversal blocked") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="actions replay not found")
    return FileResponse(
        target,
        media_type="application/x-ndjson",
        filename=f"{sample_id}.actions.jsonl",
    )


@router.get("/{batch_id}/samples/{sample_id}/screenshots/{name}")
async def download_screenshot(batch_id: str, sample_id: str, name: str) -> FileResponse:
    if not _SCREENSHOT_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid screenshot name")

    settings = get_settings()
    root = settings.logs_root.resolve()
    sample_dir = await _sample_logs_dir(batch_id, sample_id)
    if sample_dir is None:
        sample_dir = (root / batch_id / sample_id).resolve()
    target = (sample_dir / name).resolve()
    try:
        target.relative_to(sample_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path traversal blocked") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        target,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
