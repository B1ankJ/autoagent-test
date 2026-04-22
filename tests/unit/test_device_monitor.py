from datetime import datetime

import pytest

from autoagent.devices.monitor import DeviceMonitor


@pytest.mark.asyncio
async def test_sync_once_upserts_and_marks_missing_offline() -> None:
    seen = [
        [("emulator-5554", True, "sdk", "14")],
        [],
    ]

    async def fake_upsert(*, serial, model, android_version, online, seen_at):
        events.append((serial, online, model, android_version, isinstance(seen_at, datetime)))

    async def fake_mark_missing_offline(now_seen):
        gone.append(sorted(now_seen))

    events: list[tuple] = []
    gone: list[list[str]] = []

    monitor = DeviceMonitor(
        list_devices=lambda: [
            type("D", (), dict(serial=s, online=o, model=m, android_version=v))()
            for s, o, m, v in seen.pop(0)
        ],
        upsert_device=fake_upsert,
        mark_missing_offline=fake_mark_missing_offline,
        interval_sec=0.01,
    )

    await monitor.sync_once()
    await monitor.sync_once()

    assert events[0][:4] == ("emulator-5554", True, "sdk", "14")
    assert gone[-1] == []
