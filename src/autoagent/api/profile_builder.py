from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.models.api import ProfileBuilderSessionCreate, ProfileBuilderSessionView

router = APIRouter(
    prefix="/profile-builder",
    tags=["profile-builder"],
    dependencies=[Depends(require_user)],
)

_SESSIONS: dict[str, ProfileBuilderSessionView] = {}


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
    )
    _SESSIONS[session_id] = session
    return session


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session
