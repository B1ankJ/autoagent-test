from fastapi import APIRouter, Depends, HTTPException

from autoagent.auth.deps import require_user

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(require_user)])


@router.get("")
async def list_devices() -> list:
    return []


@router.post("/{serial}/connect")
async def connect(serial: str) -> dict:
    raise HTTPException(status_code=501, detail="device support arrives in plan 4")


@router.post("/{serial}/disconnect")
async def disconnect(serial: str) -> dict:
    raise HTTPException(status_code=501, detail="device support arrives in plan 4")
