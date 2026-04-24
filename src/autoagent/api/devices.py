from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from autoagent.api._deps import get_device_monitor
from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.devices.adb import (
    AdbCommandError,
    enable_ime,
    install_apk,
    is_ime_enabled,
    is_package_installed,
    set_ime,
)
from autoagent.models.api import DeviceInfo, DeviceLabelUpdate
from autoagent.storage.devices import list_devices as list_stored_devices
from autoagent.storage.devices import (
    update_device_enabled,
    update_device_label,
    upsert_discovered_device,
)

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(require_user)])


async def refresh_devices_now() -> list[DeviceInfo]:
    monitor = get_device_monitor()
    await monitor.sync_once()
    return await list_stored_devices()


async def install_adb_keyboard_for_device(serial: str) -> DeviceInfo:
    settings = get_settings()
    apk_path = settings.adb_keyboard_apk_path
    if apk_path is None:
        raise HTTPException(status_code=400, detail="ADB_KEYBOARD_APK_PATH is not configured")
    if not apk_path.exists():
        raise HTTPException(status_code=400, detail=f"ADB Keyboard APK not found: {apk_path}")

    try:
        install_apk(serial, apk_path)
    except AdbCommandError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return await upsert_discovered_device(
        serial=serial,
        model=None,
        android_version=None,
        adb_keyboard_installed=is_package_installed(serial, "com.android.adbkeyboard"),
        adb_keyboard_enabled=is_ime_enabled(serial, "com.android.adbkeyboard/.AdbIME"),
        online=True,
        seen_at=datetime.now(timezone.utc),
    )


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


@router.post("/{serial}/install-adb-keyboard", response_model=DeviceInfo)
async def install_adb_keyboard_route(serial: str) -> DeviceInfo:
    return await install_adb_keyboard_for_device(serial)


@router.post("/{serial}/enable-ime", response_model=DeviceInfo)
async def enable_ime_route(serial: str) -> DeviceInfo:
    try:
        enable_ime(serial, "com.android.adbkeyboard/.AdbIME")
        set_ime(serial, "com.android.adbkeyboard/.AdbIME")
    except AdbCommandError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return await upsert_discovered_device(
        serial=serial,
        model=None,
        android_version=None,
        adb_keyboard_installed=is_package_installed(serial, "com.android.adbkeyboard"),
        adb_keyboard_enabled=is_ime_enabled(serial, "com.android.adbkeyboard/.AdbIME"),
        online=True,
        seen_at=datetime.now(timezone.utc),
    )


@router.post("/{serial}/disable-ime", response_model=DeviceInfo)
async def disable_ime_route(serial: str) -> DeviceInfo:
    try:
        # 获取当前IME，如果是ADB Keyboard则切换到其他IME
        from autoagent.devices.adb import get_current_ime

        current = get_current_ime(serial)
        if current and "adbkeyboard" in current:
            # 切换到Android默认输入法
            set_ime(serial, "com.android.inputmethod.latin/.LatinIME")
    except AdbCommandError:
        pass  # 忽略切换失败

    return await upsert_discovered_device(
        serial=serial,
        model=None,
        android_version=None,
        adb_keyboard_installed=is_package_installed(serial, "com.android.adbkeyboard"),
        adb_keyboard_enabled=is_ime_enabled(serial, "com.android.adbkeyboard/.AdbIME"),
        online=True,
        seen_at=datetime.now(timezone.utc),
    )
