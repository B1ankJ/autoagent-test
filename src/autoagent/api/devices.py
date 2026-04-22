from fastapi import APIRouter, Depends, HTTPException

from autoagent.api._deps import get_device_monitor
from autoagent.auth.deps import require_user
from autoagent.devices.adb import AdbCommandError
from autoagent.models.api import DeviceInfo, DeviceLabelUpdate
from autoagent.storage.devices import (
    list_devices as list_stored_devices,
)
from autoagent.storage.devices import (
    update_device_enabled,
    update_device_label,
)

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(require_user)])


async def refresh_devices_now() -> list[DeviceInfo]:
    monitor = get_device_monitor()
    await monitor.sync_once()
    return await list_stored_devices()


@router.get("", response_model=list[DeviceInfo])
async def list_devices_route() -> list[DeviceInfo]:
    return await list_stored_devices()


@router.post("/refresh", response_model=list[DeviceInfo])
async def refresh_devices_route() -> list[DeviceInfo]:
    try:
        return await refresh_devices_now()
    except AdbCommandError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/{serial}/connect", response_model=DeviceInfo)
async def connect(serial: str) -> DeviceInfo:
    row = await update_device_enabled(serial, enabled=True)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


@router.post("/{serial}/disconnect", response_model=DeviceInfo)
async def disconnect(serial: str) -> DeviceInfo:
    row = await update_device_enabled(serial, enabled=False)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


@router.patch("/{serial}", response_model=DeviceInfo)
async def patch_label(serial: str, body: DeviceLabelUpdate) -> DeviceInfo:
    row = await update_device_label(serial, body.label)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row
