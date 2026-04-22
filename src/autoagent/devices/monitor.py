from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class DeviceMonitor:
    def __init__(
        self,
        *,
        list_devices,
        upsert_device,
        mark_missing_offline,
        interval_sec: float = 5.0,
    ) -> None:
        self._list_devices = list_devices
        self._upsert_device = upsert_device
        self._mark_missing_offline = mark_missing_offline
        self._interval_sec = interval_sec

    async def sync_once(self) -> None:
        now = datetime.now(timezone.utc)
        rows = self._list_devices()
        seen: set[str] = set()
        for row in rows:
            seen.add(row.serial)
            await self._upsert_device(
                serial=row.serial,
                model=row.model,
                android_version=row.android_version,
                online=row.online,
                seen_at=now,
            )
        await self._mark_missing_offline(seen)

    async def run(self) -> None:
        while True:
            try:
                await self.sync_once()
            except Exception:  # noqa: BLE001
                log.exception("device monitor sync failed")
            await asyncio.sleep(self._interval_sec)
