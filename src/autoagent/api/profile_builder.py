import asyncio
from pathlib import Path
from uuid import uuid4

import uiautomator2 as u2
from fastapi import APIRouter, Depends, HTTPException, status

from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.executors.profile_builder_capture import capture_android_state
from autoagent.models.api import ProfileBuilderSessionCreate, ProfileBuilderSessionView

router = APIRouter(
    prefix="/profile-builder",
    tags=["profile-builder"],
    dependencies=[Depends(require_user)],
)

_SESSIONS: dict[str, ProfileBuilderSessionView] = {}


def reset_sessions_for_tests() -> None:
    _SESSIONS.clear()


def _get_session_or_404(session_id: str) -> ProfileBuilderSessionView:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _artifact_names(session: ProfileBuilderSessionView) -> list[str]:
    artifact_dir = Path(session.artifact_dir)
    if not artifact_dir.exists():
        return []
    return sorted(path.name for path in artifact_dir.iterdir() if path.is_file())


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
    )
    _SESSIONS[session_id] = session
    return session


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    session = _get_session_or_404(session_id)
    if session.artifacts != _artifact_names(session):
        session = session.model_copy(update={"artifacts": _artifact_names(session)})
        _SESSIONS[session_id] = session
    return session


@router.post("/sessions/{session_id}/capture/{step}", response_model=ProfileBuilderSessionView)
async def capture_session_step(session_id: str, step: str) -> ProfileBuilderSessionView:
    session = _get_session_or_404(session_id)
    device = await asyncio.to_thread(u2.connect, session.device_serial)
    await capture_android_state(device=device, session_dir=Path(session.artifact_dir), step=step)
    updated = session.model_copy(update={"artifacts": _artifact_names(session)})
    _SESSIONS[session_id] = updated
    return updated
