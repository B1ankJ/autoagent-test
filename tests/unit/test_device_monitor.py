from datetime import datetime

import pytest

from autoagent.devices.monitor import DeviceMonitor


@pytest.mark.asyncio
async def test_sync_once_upserts_and_marks_missing_offline() -> None:
    seen = [
        [("emulator-5554", True, "sdk", "14", True, False)],
        [],
    ]

    async def fake_upsert(
        *,
        serial,
        model,
        android_version,
        adb_keyboard_installed,
        adb_keyboard_enabled,
        online,
        seen_at,
    ):
        events.append(
            (
                serial,
                online,
                model,
                android_version,
                adb_keyboard_installed,
                adb_keyboard_enabled,
                isinstance(seen_at, datetime),
            )
        )

    async def fake_mark_missing_offline(now_seen):
        gone.append(sorted(now_seen))

    events: list[tuple] = []
    gone: list[list[str]] = []

    monitor = DeviceMonitor(
        list_devices=lambda: [
            type(
                "D",
                (),
                dict(
                    serial=s,
                    online=o,
                    model=m,
                    android_version=v,
                    adb_keyboard_installed=i,
                    adb_keyboard_enabled=e,
                ),
            )()
            for s, o, m, v, i, e in seen.pop(0)
        ],
        upsert_device=fake_upsert,
        mark_missing_offline=fake_mark_missing_offline,
        interval_sec=0.01,
    )

    await monitor.sync_once()
    await monitor.sync_once()

    assert events[0][:6] == ("emulator-5554", True, "sdk", "14", True, False)
    assert gone[-1] == []


@pytest.mark.asyncio
async def test_sync_once_awaits_on_tick():
    ticked = []

    def _list():
        return []

    async def _upsert(**kw):
        pass

    async def _mark(seen):
        pass

    async def _on_tick():
        ticked.append(True)

    mon = DeviceMonitor(
        list_devices=_list, upsert_device=_upsert, mark_missing_offline=_mark, on_tick=_on_tick
    )
    await mon.sync_once()
    assert ticked == [True]
