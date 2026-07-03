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
    async def hold(self, serial: str, timeout_sec: float = 5.0):
        """Exclusively hold one specific device's lock.

        Uses the same per-serial lock as `acquire`, so a sample can't grab
        the device while it's held (and vice versa). Used to fence off a
        device during initialization. Raises DeviceBusy if the device is
        already in use (running a sample / another init) and doesn't free
        up within `timeout_sec`.
        """
        lock = self._locks.setdefault(serial, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout_sec)
        except asyncio.TimeoutError as e:
            raise DeviceBusy(
                f"device {serial} is busy (running a task or another init)"
            ) from e
        try:
            yield serial
        finally:
            lock.release()

    @asynccontextmanager
    async def acquire(
        self,
        preferred: str | None,
        timeout_sec: float = 60,
        cancel_event: asyncio.Event | None = None,
        *,
        allowed_serials: set[str] | None = None,
    ):
        """Acquire one online+enabled device from the pool.

        - `preferred` (legacy): if set, must match that exact serial.
        - `allowed_serials`: if non-empty, the pool is restricted to those
          serials. Combined with `preferred` if both are given.
        - When the resulting pool is fully offline / disabled, raises
          DeviceDisabled immediately. When the pool has online devices
          but they're all locked by other samples, polls until one frees
          up or the timeout / cancel fires.
        """
        # Merge legacy preferred + new allowed_serials into a single pool set.
        allowed: set[str] | None
        if preferred and allowed_serials:
            allowed = set(allowed_serials) | {preferred}
        elif preferred:
            allowed = {preferred}
        elif allowed_serials:
            allowed = set(allowed_serials)
        else:
            allowed = None

        deadline = time.monotonic() + timeout_sec
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise DeviceBusy("cancelled while waiting for device")
            all_devices = list(self._list_devices())
            if allowed is not None:
                pool = [d for d in all_devices if d.serial in allowed]
                if not pool:
                    raise DeviceDisabled(
                        f"no devices in pool: {sorted(allowed)}"
                    )
                if not any(d.online and d.enabled for d in pool):
                    raise DeviceDisabled(
                        f"all devices in pool offline/disabled: {sorted(allowed)}"
                    )
                candidates = [d for d in pool if d.online and d.enabled]
            else:
                candidates = [d for d in all_devices if d.online and d.enabled]

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
