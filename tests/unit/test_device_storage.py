from datetime import datetime, timezone

import pytest

from autoagent.storage.database import init_db
from autoagent.storage.devices import (
    list_devices,
    update_device_enabled,
    update_device_label,
    upsert_discovered_device,
)


@pytest.mark.asyncio
async def test_upsert_and_patch_device() -> None:
    await init_db()
    await upsert_discovered_device(
        serial="emulator-5554",
        model="sdk_gphone64_arm64",
        android_version="14",
        adb_keyboard_installed=True,
        adb_keyboard_enabled=False,
        online=True,
        seen_at=datetime.now(timezone.utc),
    )
    await update_device_label("emulator-5554", "Pixel 8 API 34")
    await update_device_enabled("emulator-5554", enabled=False)

    rows = await list_devices()
    assert [row.serial for row in rows] == ["emulator-5554"]
    assert rows[0].label == "Pixel 8 API 34"
    assert rows[0].enabled is False
    assert rows[0].online is True
    assert rows[0].adb_keyboard_installed is True
    assert rows[0].adb_keyboard_enabled is False


@pytest.mark.asyncio
async def test_upsert_discovered_device_preserves_model_and_android_version_on_none() -> None:
    """A later upsert with model=None/android_version=None (e.g. the IME
    toggle routes, which don't re-probe those fields) shouldn't clobber
    values a previous discovery already established."""
    await init_db()
    await upsert_discovered_device(
        serial="emulator-5554",
        model="sdk_gphone64_arm64",
        android_version="14",
        adb_keyboard_installed=False,
        adb_keyboard_enabled=False,
        online=True,
        seen_at=datetime.now(timezone.utc),
    )

    await upsert_discovered_device(
        serial="emulator-5554",
        model=None,
        android_version=None,
        adb_keyboard_installed=True,
        adb_keyboard_enabled=True,
        online=True,
        seen_at=datetime.now(timezone.utc),
    )

    rows = await list_devices()
    assert rows[0].model == "sdk_gphone64_arm64"
    assert rows[0].android_version == "14"
    assert rows[0].adb_keyboard_installed is True
