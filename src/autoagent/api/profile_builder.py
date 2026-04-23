from fastapi import APIRouter, status

from autoagent.models.api import ProfileBuilderSessionCreate, ProfileBuilderSessionView

router = APIRouter(prefix="/profile-builder", tags=["profile-builder"])


@router.post("/sessions", response_model=ProfileBuilderSessionView, status_code=status.HTTP_201_CREATED)
async def create_session(payload: ProfileBuilderSessionCreate) -> ProfileBuilderSessionView:
    return ProfileBuilderSessionView(
        id="pb_demo",
        platform=payload.platform,
        device_serial=payload.device_serial,
        name=payload.name,
        status="draft",
        steps=["idle", "editing", "response"],
        artifact_dir="data/profile_builder/pb_demo",
    )


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    return ProfileBuilderSessionView(
        id=session_id,
        platform="android",
        device_serial="serial-1",
        name="qwen",
        status="draft",
        steps=["idle", "editing", "response"],
        artifact_dir=f"data/profile_builder/{session_id}",
    )
