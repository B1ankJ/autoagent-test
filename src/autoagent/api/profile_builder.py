import asyncio
from pathlib import Path
from uuid import uuid4

import uiautomator2 as u2
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.executors.profile_builder_capture import CapturedState, capture_android_state
from autoagent.models.api import (
    ProfileBuilderCaptureArtifact,
    ProfileBuilderSessionCreate,
    ProfileBuilderSessionView,
)

router = APIRouter(
    prefix="/profile-builder",
    tags=["profile-builder"],
    dependencies=[Depends(require_user)],
)

_SESSIONS: dict[str, ProfileBuilderSessionView] = {}


def reset_sessions_for_tests() -> None:
    _SESSIONS.clear()


def _session_dir(session_id: str) -> Path:
    return get_settings().data_root / "profile_builder" / session_id


def _session_json_path(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _artifact_names(session: ProfileBuilderSessionView) -> list[str]:
    artifact_dir = Path(session.artifact_dir)
    if not artifact_dir.exists():
        return []
    return sorted(
        path.name
        for path in artifact_dir.iterdir()
        if path.is_file() and path.name != "session.json"
    )


def _persist_session(session: ProfileBuilderSessionView) -> None:
    artifact_dir = Path(session.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    session_json = artifact_dir / "session.json"
    session_tmp = artifact_dir / "session.json.tmp"
    session_tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    session_tmp.replace(session_json)


def _load_session_from_disk(session_id: str) -> ProfileBuilderSessionView | None:
    session_json = _session_json_path(session_id)
    if not session_json.exists():
        return None
    try:
        return ProfileBuilderSessionView.model_validate_json(session_json.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise HTTPException(status_code=500, detail="profile builder session load failed") from exc


def _sync_artifacts(session: ProfileBuilderSessionView) -> ProfileBuilderSessionView:
    artifacts = _artifact_names(session)
    if session.artifacts == artifacts:
        return session
    return session.model_copy(update={"artifacts": artifacts})


def _store_session(session: ProfileBuilderSessionView) -> ProfileBuilderSessionView:
    synced = _sync_artifacts(session)
    _persist_session(synced)
    _SESSIONS[synced.id] = synced
    return synced


def _get_session_or_404(session_id: str) -> ProfileBuilderSessionView:
    session = _load_session_from_disk(session_id)
    if session is None:
        session = _SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
    synced = _sync_artifacts(session)
    if synced != session:
        _persist_session(synced)
    _SESSIONS[session_id] = synced
    return synced


def _validate_capture_step(session: ProfileBuilderSessionView, step: str) -> None:
    if step not in session.steps:
        raise HTTPException(status_code=422, detail=f"unknown capture step: {step}")


def _capture_artifact_from_state(captured: CapturedState) -> ProfileBuilderCaptureArtifact:
    return ProfileBuilderCaptureArtifact(
        step=captured.step,
        package=captured.package,
        activity=captured.activity,
        xml_artifact=captured.xml_path.name,
        screenshot_artifact=captured.screenshot_path.name,
    )


@router.post("/sessions", response_model=ProfileBuilderSessionView, status_code=status.HTTP_201_CREATED)
async def create_session(payload: ProfileBuilderSessionCreate) -> ProfileBuilderSessionView:
    session_id = f"pb_{uuid4().hex[:12]}"
    session = ProfileBuilderSessionView(
        id=session_id,
        platform=payload.platform,
        device_serial=payload.device_serial,
        name=payload.name,
        status="draft",
        steps=["idle", "editing", "response"],
        artifact_dir=str(get_settings().data_root / "profile_builder" / session_id),
        artifacts=[],
        captures=[],
    )
    return _store_session(session)


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    return _get_session_or_404(session_id)


@router.post("/sessions/{session_id}/capture/{step}", response_model=ProfileBuilderSessionView)
async def capture_session_step(session_id: str, step: str) -> ProfileBuilderSessionView:
    session = _get_session_or_404(session_id)
    _validate_capture_step(session, step)
    try:
        device = await asyncio.to_thread(u2.connect, session.device_serial)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"profile builder capture connect failed: {exc}",
        ) from exc

    try:
        captured = await capture_android_state(
            device=device,
            session_dir=Path(session.artifact_dir),
            step=step,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"profile builder capture failed: {exc}",
        ) from exc

    capture_record = _capture_artifact_from_state(captured)
    captures = [record for record in session.captures if record.step != step]
    captures.append(capture_record)
    captures.sort(key=lambda record: session.steps.index(record.step))
    updated = session.model_copy(update={"captures": captures})
    return _store_session(updated)
