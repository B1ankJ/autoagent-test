from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager

from autoagent.models.api import DeviceInfo

# Session-pin bookkeeping (see DevicePool.acquire's session_id docs). TTL is
# a fallback for callers that never explicitly release (crash, forgot,
# whatever) — release_session() is the clean path. Bounded like
# login_throttle.py's failure counter so a caller flooding distinct
# session_ids can't grow this unboundedly.
_SESSION_TTL_SEC = 1800.0
_MAX_SESSIONS = 10_000


class DeviceBusy(RuntimeError):
    pass


class DeviceDisabled(RuntimeError):
    pass


class DevicePool:
    def __init__(self, list_devices: Callable[[], list[DeviceInfo]] | None = None) -> None:
        self._snapshot: dict[str, DeviceInfo] = {}
        self._list_devices = list_devices or (lambda: list(self._snapshot.values()))
        self._locks: dict[str, asyncio.Lock] = {}
        self._session_pins: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def update_snapshot(self, devices: list[DeviceInfo]) -> None:
        self._snapshot = {device.serial: device for device in devices}

    def available_count_sync(self) -> int:
        count = 0
        for device in self._list_devices():
            lock = self._locks.get(device.serial)
            if device.online and device.enabled and (lock is None or not lock.locked()):
                count += 1
        return count

    def _lookup_pin(self, session_id: str) -> str | None:
        entry = self._session_pins.get(session_id)
        if entry is None:
            return None
        serial, expires_at = entry
        if expires_at <= time.monotonic():
            del self._session_pins[session_id]
            return None
        return serial

    def _remember_pin(self, session_id: str, serial: str) -> None:
        self._session_pins[session_id] = (serial, time.monotonic() + _SESSION_TTL_SEC)
        self._session_pins.move_to_end(session_id)
        while len(self._session_pins) > _MAX_SESSIONS:
            self._session_pins.popitem(last=False)

    def _reserved_serials(self, *, exclude_session: str) -> set[str]:
        now = time.monotonic()
        return {
            serial
            for sid, (serial, expires_at) in self._session_pins.items()
            if sid != exclude_session and expires_at > now
        }

    def release_session(self, session_id: str) -> bool:
        """Explicitly free a session's device pin. Returns whether one existed.

        Not finding one (already released, expired, or never pinned) isn't
        an error — calling this is meant to be safe to do unconditionally
        once a caller's conversation is done.
        """
        return self._session_pins.pop(session_id, None) is not None

    @asynccontextmanager
    async def hold(self, serial: str, timeout_sec: float = 5.0):
        """Exclusively hold one specific device's lock.

        Uses the same per-serial lock as `acquire`, so a sample can't grab
        the device while it's held (and vice versa). Used to fence off a
        device during initialization. Raises DeviceBusy if the device is
        already in use (running a task / another init) and doesn't free
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
        session_id: str | None = None,
        new_session: bool = False,
    ):
        """Acquire one online+enabled device from the pool.

        - `preferred` (legacy): if set, must match that exact serial.
        - `allowed_serials`: if non-empty, the pool is restricted to those
          serials. Combined with `preferred` if both are given.
        - `session_id`/`new_session`: opt-in multi-turn device stickiness
          for a conversation split across separate requests (Sample.
          session_id). Leaving `session_id` unset (the default) is
          byte-for-byte the original preferred/allowed_serials-only
          behavior — nothing below this point runs. When set:
          `new_session=True` picks a device normally, except it skips
          devices currently pinned to a *different* session_id (so it
          doesn't steal another in-flight conversation's device), then
          pins `session_id` to whichever device it lands on.
          `new_session=False` with an existing, unexpired pin for
          `session_id` forces that exact device — waits if it's busy,
          raises DeviceDisabled if it's gone, never silently substitutes
          a different device (which would silently break conversation
          continuity). `new_session=False` with no/expired pin falls back
          to normal selection and self-heals a new pin. Pins expire after
          `_SESSION_TTL_SEC` of inactivity as a fallback for callers that
          never call `release_session`; call it explicitly when a
          conversation legitimately ends to free the device sooner.
        - When the resulting pool is fully offline / disabled, raises
          DeviceDisabled immediately. When the pool has online devices
          but they're all locked by other samples, polls until one frees
          up or the timeout / cancel fires.
        """
        effective_preferred = preferred
        effective_allowed = allowed_serials
        exclude: set[str] = set()

        if session_id is not None:
            pinned = None if new_session else self._lookup_pin(session_id)
            if pinned is not None:
                effective_preferred = pinned
                effective_allowed = None
            else:
                exclude = self._reserved_serials(exclude_session=session_id)

        # Merge legacy preferred + new allowed_serials into a single pool set.
        allowed: set[str] | None
        if effective_preferred and effective_allowed:
            allowed = set(effective_allowed) | {effective_preferred}
        elif effective_preferred:
            allowed = {effective_preferred}
        elif effective_allowed:
            allowed = set(effective_allowed)
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
            if exclude:
                # Soft preference, not a hard block: avoid a device another
                # session has reserved only when there's an alternative.
                # Otherwise a fully (or singly-)reserved pool would starve
                # every *other* new conversation until the reservation's
                # TTL expires, even though nothing is actually locked.
                unreserved = [d for d in candidates if d.serial not in exclude]
                if unreserved:
                    candidates = unreserved

            for device in candidates:
                lock = self._locks.setdefault(device.serial, asyncio.Lock())
                if lock.locked():
                    continue
                await lock.acquire()
                if session_id is not None:
                    self._remember_pin(session_id, device.serial)
                try:
                    yield device.serial
                finally:
                    lock.release()
                return

            if time.monotonic() >= deadline:
                raise DeviceBusy(f"no device available within {timeout_sec}s")
            await asyncio.sleep(0.1)
