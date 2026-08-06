from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from autoagent.devices import adb
from autoagent.devices.adb import _is_network_serial
from autoagent.devices.expected_state import is_expected_reboot

log = logging.getLogger(__name__)

_HEAL_INITIAL_SEC = 30.0
_HEAL_MAX_SEC = 300.0


class DeviceHealer:
    """Auto-reconnects offline network (wifi) devices via `adb connect` on the
    device-monitor tick, with per-serial exponential backoff. Opt-in and safe:
    reconnect only, no reboot; skips USB / disabled / planned-reboot / in-use
    devices; a single connect failure never aborts the tick."""

    def __init__(
        self,
        *,
        list_devices: Callable[[], Awaitable[list]],
        is_locked: Callable[[str], bool],
        is_enabled: Callable[[], Awaitable[bool]],
        connect: Callable[[str], None] = adb.connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._list_devices = list_devices
        self._is_locked = is_locked
        self._is_enabled = is_enabled
        self._connect = connect
        self._clock = clock
        self._next_attempt: dict[str, float] = {}
        self._backoff: dict[str, float] = {}

    async def maybe_heal(self) -> None:
        try:
            if not await self._is_enabled():
                return
            rows = await self._list_devices()
        except Exception:  # noqa: BLE001
            log.exception("device auto-heal: enabled/list check failed")
            return

        now = self._clock()
        for d in rows:
            serial = d.serial
            if d.online:
                self._next_attempt.pop(serial, None)
                self._backoff.pop(serial, None)
                continue
            if not _is_network_serial(serial) or not d.enabled:
                continue
            if is_expected_reboot(serial) or self._is_locked(serial):
                continue
            if now < self._next_attempt.get(serial, 0.0):
                continue
            try:
                await asyncio.to_thread(self._connect, serial)
                log.info("device auto-heal: adb connect %s", serial)
            except Exception:  # noqa: BLE001
                log.warning("device auto-heal: adb connect %s failed", serial, exc_info=True)
            prev = self._backoff.get(serial)
            backoff = _HEAL_INITIAL_SEC if prev is None else min(prev * 2, _HEAL_MAX_SEC)
            self._backoff[serial] = backoff
            self._next_attempt[serial] = now + backoff
