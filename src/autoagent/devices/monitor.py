from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
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
        on_state_change: Callable[[str, str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._list_devices = list_devices
        self._upsert_device = upsert_device
        self._mark_missing_offline = mark_missing_offline
        self._interval_sec = interval_sec
        # Optional hook fired on any online↔offline / online↔missing transition
        # for a given serial. Called as (serial, prev_state, new_state) where
        # states are "online", "offline", "missing". Never raises out; the
        # monitor swallows callback exceptions to avoid stalling the loop.
        self._on_state_change = on_state_change
        # Per-serial last-known state, populated as we observe devices. Not
        # persisted — first tick after restart just seeds it, no transitions
        # emitted yet.
        self._last_state: dict[str, str] = {}
        self._seeded = False

    async def sync_once(self) -> None:
        now = datetime.now(timezone.utc)
        # Adb calls are synchronous subprocess.run — must run off the event
        # loop or a hung wifi device will freeze the whole uvicorn process,
        # including the startup handshake.
        rows = await asyncio.to_thread(self._list_devices)
        seen: set[str] = set()
        current: dict[str, str] = {}
        for row in rows:
            seen.add(row.serial)
            current[row.serial] = "online" if row.online else "offline"
            await self._upsert_device(
                serial=row.serial,
                model=row.model,
                android_version=row.android_version,
                adb_keyboard_installed=row.adb_keyboard_installed,
                adb_keyboard_enabled=row.adb_keyboard_enabled,
                online=row.online,
                seen_at=now,
            )
        await self._mark_missing_offline(seen)
        # Any serial that WAS known but isn't in this tick is now "missing"
        # (adb doesn't list it at all — device unplugged / network gone).
        for serial in self._last_state:
            if serial not in current:
                current[serial] = "missing"
        await self._emit_transitions(current)
        self._last_state = current

    async def _emit_transitions(self, current: dict[str, str]) -> None:
        if self._on_state_change is None:
            return
        if not self._seeded:
            # First tick just captures the initial state; skip emitting so
            # a fresh boot doesn't fire "offline" for every device that was
            # already offline at startup.
            self._seeded = True
            return
        for serial, new_state in current.items():
            prev = self._last_state.get(serial)
            if prev is None or prev == new_state:
                continue
            try:
                await self._on_state_change(serial, prev, new_state)
            except Exception:  # noqa: BLE001
                log.exception("on_state_change hook failed for %s", serial)

    async def run(self) -> None:
        while True:
            try:
                await self.sync_once()
            except Exception:  # noqa: BLE001
                log.exception("device monitor sync failed")
            await asyncio.sleep(self._interval_sec)
