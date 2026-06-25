from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from autoagent.models.api import DeviceInfo


class DeviceBusy(RuntimeError):
    pass


class DeviceDisabled(RuntimeError):
    pass


class DevicePool:
    def __init__(self, list_devices: Callable[[], list[DeviceInfo]] | None = None) -> None:
        self._snapshot: dict[str, DeviceInfo] = {}
        self._list_devices = list_devices or (lambda: list(self._snapshot.values()))
        self._locks: dict[str, asyncio.Lock] = {}

    def update_snapshot(self, devices: list[DeviceInfo]) -> None:
        self._snapshot = {device.serial: device for device in devices}

    def available_count_sync(self) -> int:
        count = 0
        for device in self._list_devices():
            lock = self._locks.get(device.serial)
            if device.online and device.enabled and (lock is None or not lock.locked()):
                count += 1
        return count

    @asynccontextmanager
    async def acquire(
        self,
        preferred: str | None,
        timeout_sec: float = 60,
        cancel_event: asyncio.Event | None = None,
    ):
        deadline = time.monotonic() + timeout_sec
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise DeviceBusy("cancelled while waiting for device")
            candidates = [
                device for device in self._list_devices() if device.online and device.enabled
            ]
            if preferred:
                if any(
                    device.serial == preferred and not device.enabled
                    for device in self._list_devices()
                ):
                    raise DeviceDisabled(f"device {preferred} unavailable")
                candidates = [device for device in candidates if device.serial == preferred]
                if not candidates:
                    raise DeviceDisabled(f"device {preferred} unavailable")

            for device in candidates:
                lock = self._locks.setdefault(device.serial, asyncio.Lock())
                if lock.locked():
                    continue
                await lock.acquire()
                try:
                    yield device.serial
                finally:
                    lock.release()
                return

            if time.monotonic() >= deadline:
                raise DeviceBusy(f"no device available within {timeout_sec}s")
            await asyncio.sleep(0.1)
