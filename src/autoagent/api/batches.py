from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
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
    Sample,
    ScreenshotInfo,
)
from autoagent.openai_compat.chat_completions import select_effective_response
from autoagent.storage.batches import (
    batch_profiles_and_devices,
    count_batches_by_status,
    delete_batch_rows,
    get_batch,
    list_batches,
    update_batch_status,
)
from autoagent.storage.samples import list_samples_for_batch

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_user)])
# Accept both .png (legacy batches) and .jpg (current, JPEG-compressed).
_SCREENSHOT_RE = re.compile(r"^[a-z0-9_]+\.(png|jpg)$")
_STAGE_ORDER = {
    "before_input": 0,
    "after_input": 1,
    "after_send": 2,
    "after_result": 3,
    "done": 4,
    "on_error": 5,
}


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _screenshot_order_key(name: str) -> tuple[int, int, str]:
    stem = Path(name).stem
    for prefix, order in _STAGE_ORDER.items():
        if stem == prefix:
            return (order, 0, name)
        if stem.startswith(f"{prefix}_"):
            suffix = stem[len(prefix) + 1 :]
            try:
                step = int(suffix)
            except ValueError:
                step = 0
            return (order, step, name)
    return (99, 0, name)


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


@router.get("/stats")
async def batch_stats(
    q: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    target_profile: str | None = None,
    device_serial: str | None = None,
    empty_response_only: bool = False,
) -> dict[str, int]:
    """Aggregate counts across all batches, independent of list pagination.

    Returns {"total": N, "queued": .., "running": .., "done": .., "failed": ..,
    "cancelled": ..}. Filter args mirror /batches so the dashboard cards
    stay consistent with the visible list.
    """
    counts = await count_batches_by_status(
        q=q or None,
        created_after=created_after,
        created_before=created_before,
        target_profile=target_profile or None,
        device_serial=device_serial or None,
        empty_response_only=empty_response_only,
    )
    for status in ("queued", "running", "done", "failed", "cancelled"):
        counts.setdefault(status, 0)
    return counts


_PREVIEW_PROMPT_MAX = 160


def _truncate(text: str) -> str:
    clean = text.replace("\n", " ").strip()
    if len(clean) > _PREVIEW_PROMPT_MAX:
        return clean[:_PREVIEW_PROMPT_MAX] + "…"
    return clean


async def _single_sample_preview(batch_id: str) -> tuple[str | None, str | None]:
    """Return (prompt, response) previews for a single-sample batch.

    Each element is:
      - None  → not applicable (no sample, or prompt absent)
      - str   → truncated text (empty string means "ran but produced nothing"
                — the frontend uses that to flag an anomaly)
    """
    samples = await list_samples_for_batch(batch_id)
    if not samples:
        return None, None
    sample = samples[0]
    prompt_raw = (sample.prompts_sent or [None])[0]
    prompt = _truncate(prompt_raw) if isinstance(prompt_raw, str) and prompt_raw.strip() else None
    if prompt is None:
        # No usable prompt → don't bother surfacing the response either.
        return None, None
    # Same priority as select_message_content (what /v1/chat/completions
    # actually returns): prefer the LLM-reviewed response when extraction
    # ran and succeeded. Previewing responses[0] unconditionally used to
    # show the raw extraction even when the real answer was the LLM one.
    response_raw = select_effective_response(
        sample.responses, sample.llm_responses, sample.llm_errors
    )
    response = _truncate(response_raw) if response_raw else ""
    return prompt, response


@router.get("", response_model=list[BatchSummary])
async def list_all(
    # 200 matches the UI's own largest page-size option (List.tsx
    # pageSizeOptions) — capped so a crafted/huge limit can't force a
    # multi-thousand-row scan + per-row preview/profile aggregation.
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    target_profile: str | None = None,
    device_serial: str | None = None,
    empty_response_only: bool = False,
) -> list[BatchSummary]:
    rows = await list_batches(
        limit=limit,
        offset=offset,
        q=q or None,
        created_after=created_after,
        created_before=created_before,
        target_profile=target_profile or None,
        device_serial=device_serial or None,
        empty_response_only=empty_response_only,
    )
    # One aggregate query for the whole page's profiles + devices.
    pd_map = await batch_profiles_and_devices([r.id for r in rows])
    summaries: list[BatchSummary] = []
    for r in rows:
        if r.total == 1:
            preview, response = await _single_sample_preview(r.id)
        else:
            preview, response = None, None
        profiles, devices = pd_map.get(r.id, ([], []))
        summaries.append(
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
                preview_prompt=preview,
                preview_response=response,
                profiles=profiles,
                devices=devices,
            )
        )
    return summaries


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
async def download_results(batch_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    """Return a zip containing the batch JSONL + the entire logs/<batch>/ tree.

    Layout in the zip:
      <batch_id>.jsonl                 ← per-sample results, one line each
      logs/<sample_id>/...             ← screenshots, XML dumps, action logs

    Either piece is included only if it exists on disk, so a still-running
    batch downloads whatever artifacts have landed so far. A truly empty
    batch (no JSONL, no logs dir) returns 404.
    """
    b = await get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    settings = get_settings()
    jsonl_path = settings.data_root / "results" / f"{batch_id}.jsonl"
    logs_dir = settings.logs_root / batch_id

    if not jsonl_path.exists() and not logs_dir.exists():
        raise HTTPException(status_code=404, detail="no results or logs found")

    tmp = tempfile.NamedTemporaryFile(prefix=f"{batch_id}_", suffix=".zip", delete=False)
    tmp.close()
    try:
        # Screenshots dominate; PNG bytes don't compress further but action
        # logs / XML do, so DEFLATE is still a net win at minimal CPU cost.
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if jsonl_path.exists():
                zf.write(jsonl_path, arcname=f"{batch_id}.jsonl")
            if logs_dir.exists():
                for file_path in sorted(logs_dir.rglob("*")):
                    if file_path.is_file():
                        zf.write(
                            file_path,
                            arcname=f"logs/{file_path.relative_to(logs_dir)}",
                        )
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise

    background_tasks.add_task(Path(tmp.name).unlink, missing_ok=True)
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"{batch_id}.zip",
    )


@router.post("/{batch_id}/rerun", response_model=BatchCreatedResponse, status_code=201)
async def rerun(batch_id: str, status: str = "failed") -> BatchCreatedResponse:
    """Submit a new batch reusing samples from `batch_id` with the given status.

    Default `status=failed` covers the common "re-run only failures" case;
    `status=all` re-runs every sample regardless of outcome. Sample metadata
    that wasn't persisted (retry/timeout_sec/new_session/callback_url) falls
    back to defaults — users who need finer control should rebuild the batch.
    """
    if status not in {"failed", "all", "timeout", "extraction_failed", "cancelled"}:
        raise HTTPException(status_code=400, detail=f"unsupported status filter: {status!r}")

    original = await get_batch(batch_id)
    if original is None:
        raise HTTPException(status_code=404, detail="batch not found")

    results = await list_samples_for_batch(batch_id)
    if status == "all":
        chosen = results
    else:
        chosen = [r for r in results if r.status == status]
    if not chosen:
        raise HTTPException(status_code=400, detail=f"no samples with status={status}")

    samples = [
        Sample(
            id=r.id,
            prompts=r.prompts_sent or [""],
            mode=r.mode,
            target_profile=r.target_profile,
        )
        for r in chosen
    ]
    sch = get_scheduler()
    new_id = await sch.submit(
        name=f"{original.name} (rerun {status})",
        mode=original.mode,  # type: ignore[arg-type]
        concurrency=original.concurrency,
        samples=samples,
        target_profile_default=original.target_profile_default,
    )
    return BatchCreatedResponse(batch_id=new_id)


@router.post("/{batch_id}/replay", response_model=BatchCreatedResponse, status_code=201)
async def replay(batch_id: str) -> BatchCreatedResponse:
    """Resubmit `batch_id` with an identical Sample list to the one originally
    submitted — every field (new_session/timeout_sec/retry/dry_run/
    callback_url/metadata), not just prompts/mode/target_profile like
    `/rerun`. Requires the batch to have been created after replay support
    shipped (samples_request_json populated); older batches don't have this
    recorded and should use /rerun instead.
    """
    original = await get_batch(batch_id)
    if original is None:
        raise HTTPException(status_code=404, detail="batch not found")
    if not original.samples_request_json:
        raise HTTPException(
            status_code=400,
            detail="this batch predates replay support and has no recorded "
            "request to replay; use /rerun instead",
        )
    try:
        raw_samples = json.loads(original.samples_request_json)
        samples = [Sample.model_validate(s) for s in raw_samples]
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=500, detail=f"stored replay request is corrupt: {e}"
        ) from e

    sch = get_scheduler()
    new_id = await sch.submit(
        name=f"{original.name} (replay)",
        mode=original.mode,  # type: ignore[arg-type]
        concurrency=original.concurrency,
        samples=samples,
        target_profile_default=original.target_profile_default,
    )
    return BatchCreatedResponse(batch_id=new_id)


@router.post("/{batch_id}/cancel", status_code=202)
async def cancel(batch_id: str) -> dict:
    sch = get_scheduler()
    ok = await sch.cancel(batch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="batch not found or already finished")
    return {"batch_id": batch_id, "status": "cancelling"}


def _purge_batch_artifacts(batch_id: str) -> None:
    """Best-effort filesystem cleanup for a batch: JSONL result + logs dir."""
    settings = get_settings()
    result_path = settings.data_root / "results" / f"{batch_id}.jsonl"
    logs_dir = settings.logs_root / batch_id
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        shutil.rmtree(logs_dir, ignore_errors=True)
    except OSError:
        pass


@router.delete("/{batch_id}", status_code=204)
async def delete_batch_endpoint(batch_id: str) -> None:
    batch = await get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    if batch.status in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail="batch is active; cancel it first then delete",
        )
    await delete_batch_rows(batch_id)
    _purge_batch_artifacts(batch_id)


@router.post("/delete-by-status", status_code=200)
async def delete_by_status(status: str) -> dict:
    """Bulk delete all batches matching one of the terminal statuses.

    Accepts: done | failed | cancelled | terminal (= done+failed+cancelled).
    Refuses queued / running to keep callers from foot-gunning active work.
    """
    allowed = {"done", "failed", "cancelled", "terminal"}
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(allowed)}",
        )
    targets = {"done", "failed", "cancelled"} if status == "terminal" else {status}
    rows = await list_batches(limit=10000, offset=0, q=None)
    matching = [r for r in rows if r.status in targets]
    deleted = 0
    for row in matching:
        if await delete_batch_rows(row.id):
            _purge_batch_artifacts(row.id)
            deleted += 1
    return {"deleted": deleted, "matched": len(matching)}


@router.post("/cancel-active", status_code=202)
async def cancel_active() -> dict:
    """Cancel every queued/running batch in one call.

    Live batches are cancelled via the scheduler (drops the cancel_event so
    in-flight samples exit cleanly). Orphaned rows — `status=running` in DB
    but the scheduler has no in-memory state, typical after a uvicorn
    restart mid-batch — are flipped to `cancelled` directly so the UI stops
    showing them as alive.
    """
    sch = get_scheduler()
    rows = await list_batches(limit=10000, offset=0, q=None)
    active = [r for r in rows if r.status in ("queued", "running")]
    cancelled = 0
    orphaned = 0
    for row in active:
        if await sch.cancel(row.id):
            cancelled += 1
        else:
            await update_batch_status(row.id, "cancelled")
            orphaned += 1
    return {"cancelled": cancelled, "orphaned": orphaned, "total": len(active)}


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
        key=lambda entry: (
            0 if entry.name in order_map else 1,
            order_map.get(entry.name, 10_000),
            _screenshot_order_key(entry.name),
        ),
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


@router.get("/{batch_id}/samples/{sample_id}/logs.zip")
async def download_sample_logs(
    batch_id: str, sample_id: str, background_tasks: BackgroundTasks
) -> FileResponse:
    """Return a zip of every file in logs/<batch_id>/<sample_id>/.

    Includes screenshots, XML dumps, action_log.jsonl / actions.jsonl,
    executor.log, llm_extract_*.json — everything captured for that one
    sample. Useful for sharing a single failing case without exporting
    the whole batch.
    """
    root = get_settings().logs_root.resolve()
    sample_dir = await _sample_logs_dir(batch_id, sample_id)
    if sample_dir is None:
        sample_dir = (root / batch_id / sample_id).resolve()
    if not sample_dir.is_dir():
        raise HTTPException(status_code=404, detail="sample logs not found")
    # Defence in depth against ../ smuggling through batch_id / sample_id.
    try:
        sample_dir.relative_to(root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path traversal blocked") from e

    tmp = tempfile.NamedTemporaryFile(
        prefix=f"{batch_id}_{sample_id}_", suffix=".zip", delete=False
    )
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            wrote_any = False
            for file_path in sorted(sample_dir.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, arcname=str(file_path.relative_to(sample_dir)))
                    wrote_any = True
            if not wrote_any:
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=404, detail="sample logs are empty")
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise

    background_tasks.add_task(Path(tmp.name).unlink, missing_ok=True)
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"{sample_id}.zip",
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
    media_type = "image/jpeg" if target.suffix.lower() == ".jpg" else "image/png"
    return FileResponse(
        target,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
