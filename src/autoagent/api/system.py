"""System self-update endpoints: check origin/main and apply + restart.

Gated behind DefaultsConfig.self_update_enabled and admin auth (router-level
require_user). Applying an update interrupts any in-flight batch, so /apply
refuses unless there are none or force=true is passed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.models.api import DefaultsConfig
from autoagent.storage.batches import count_active_batches
from autoagent.storage.configs import get_config
from autoagent.system import updater
from autoagent.utils.tail import tail_lines

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_user)])


async def _self_update_enabled() -> bool:
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    return cfg.self_update_enabled


@router.get("/update/status")
async def update_status() -> dict:
    """Cached local-vs-remote status. Does not hit the network (no fetch)."""
    enabled = await _self_update_enabled()
    status = await asyncio.to_thread(updater.check_for_update, enabled=enabled, do_fetch=False)
    return asdict(status)


@router.get("/update/preflight")
async def update_preflight() -> dict:
    """Diagnose the box (git/uv/pnpm reachable, remote pullable, clean tree).

    Read-only, so it's allowed regardless of the self_update_enabled flag —
    admins can check readiness before turning self-update on.
    """
    result = await asyncio.to_thread(updater.preflight)
    return asdict(result)


@router.post("/update/check")
async def update_check() -> dict:
    """Fetch origin/main and report whether an update is available."""
    enabled = await _self_update_enabled()
    if not enabled:
        raise HTTPException(status_code=403, detail="self-update is disabled")
    status = await asyncio.to_thread(updater.check_for_update, enabled=enabled, do_fetch=True)
    return asdict(status)


class _ApplyRequest(BaseModel):
    force: bool = False


@router.post("/update/apply")
async def update_apply(body: _ApplyRequest) -> dict:
    enabled = await _self_update_enabled()
    if not enabled:
        raise HTTPException(status_code=403, detail="self-update is disabled")

    active = await count_active_batches()
    if active > 0 and not body.force:
        # 409: caller must confirm interrupting in-flight batches with force=true.
        raise HTTPException(
            status_code=409,
            detail={"error": "active_batches", "active_batches": active},
        )

    _log.warning(
        "self-update: applying origin/main (force=%s, active_batches=%d)", body.force, active
    )
    result = await asyncio.to_thread(updater.apply_update)
    payload = asdict(result)
    payload["active_batches"] = active
    if not result.ok:
        raise HTTPException(status_code=500, detail=payload)
    return payload


@router.get("/log")
async def read_app_log(lines: int = Query(default=1000, ge=50, le=10000)) -> dict:
    """Tail the app's own runtime log (Settings.log_file).

    That file is the raw stdout+stderr of the whole uvicorn/FastAPI process
    (app log lines plus uvicorn's own startup/access/error output) —
    written by run.sh's `>>"$LOG_FILE" 2>&1` redirect, not by Python itself.
    It has no rotation, so this always tails rather than risking loading a
    multi-GB file into memory.
    """
    path = get_settings().log_file
    content, truncated = await asyncio.to_thread(tail_lines, path, lines)
    exists = path.exists()
    return {
        "path": str(path.resolve()),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "truncated": truncated,
        "content": content,
    }


@router.get("/log/download")
async def download_app_log() -> FileResponse:
    path = get_settings().log_file
    if not path.exists():
        raise HTTPException(status_code=404, detail="log file not found")
    return FileResponse(path, filename="autoagent.log", media_type="text/plain")
