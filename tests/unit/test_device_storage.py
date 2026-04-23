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
