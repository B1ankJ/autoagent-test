# Device Watchdog / Auto-Heal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opt-in auto-reconnect (`adb connect`) for offline network devices, with exponential backoff and safety exclusions, riding the existing `DeviceMonitor` poll loop.

**Architecture:** New `devices/healer.py::DeviceHealer` (fully injected deps) invoked each `DeviceMonitor` tick via a new `on_tick` hook; gated by `DefaultsConfig.device_autoheal_enabled`; excludes USB/disabled/planned-reboot/pool-locked devices. Config-page toggle only; reuses the existing offline/online DingTalk transitions.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (SQLite), `uv`; React 18 + TS + AntD 5, Vitest.

---

## Context an implementer needs

- **`devices/adb.py`**: `connect(target)` (`adb connect target`), `_is_network_serial(serial) -> bool` (`":" in serial and not serial.startswith(":")` — host:port = wifi). adb calls are **blocking subprocess** → always run via `asyncio.to_thread`.
- **`devices/expected_state.py::is_expected_reboot(serial) -> bool`** — a planned init/reboot is in progress for this serial.
- **`devices/pool.py::DevicePool`**: per-serial `asyncio.Lock` in `self._locks`; `hold(serial, timeout_sec)` is an async context manager that acquires that lock. No public "is locked" query yet.
- **`devices/monitor.py::DeviceMonitor`**: `sync_once()` polls adb, upserts DB, `_emit_transitions`, sets `self._last_state = current`. `run()` loops every `interval_sec` (5s), guarded. Construction params: `list_devices, upsert_device, mark_missing_offline, interval_sec, on_state_change`.
- **`api/_deps.py::get_device_monitor`**: builds the singleton `DeviceMonitor` with `list_devices=adb_list_devices`, DB upsert/mark-missing closures, and `on_state_change=on_device_state_change`. `get_device_pool()` returns the shared `DevicePool`. `list_stored_devices` (imported there as `list_devices as list_stored_devices`) returns `list[DeviceInfo]` (DB rows with `.serial/.online/.enabled`).
- **`DefaultsConfig`** (`models/api.py`): the kv `"defaults"` config; `GET/PUT /api/v1/config/defaults` round-trip it. Fields are simple typed defaults (e.g. `verbose_logs: bool = True`, `self_update_enabled` etc.). Read via `get_config("defaults")` + `DefaultsConfig.model_validate(...)`.
- **Frontend**: `GlobalDefaults` TS interface in `web/src/types/api.ts` (has `verbose_logs?`, `self_update_enabled?`…). `Config.tsx` has a `defaultsForm` (`Form<GlobalDefaults>`), with `Switch` `Form.Item`s like `name="verbose_logs"`/`name="self_update_enabled"` (both `valuePropName="checked"`).
- **Tests**: `pytest-asyncio` auto mode. There's a `tests/unit/test_device_pool.py` and `tests/unit/test_device_monitor.py` (check names; monitor/pool have existing unit tests to mirror). Run `uv run pytest -q <path>`; lint `uv run ruff check <files>; echo EXIT=$?`. Frontend `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`. pnpm cwd resets → prefix `cd .../web &&`.

---

## File Structure

- Modify `src/autoagent/models/api.py` (`DefaultsConfig.device_autoheal_enabled`)
- Modify `src/autoagent/devices/pool.py` (`is_locked`)
- Create `src/autoagent/devices/healer.py` (`DeviceHealer`)
- Modify `src/autoagent/devices/monitor.py` (`on_tick` hook)
- Modify `src/autoagent/api/_deps.py` (construct + inject the healer)
- Modify `web/src/types/api.ts`, `web/src/pages/Config.tsx` (Switch)
- Tests: `tests/unit/test_device_pool.py` (extend), `tests/unit/test_device_healer.py` (new), `tests/unit/test_device_monitor.py` (extend)

---

## Task 1: Config field + `DevicePool.is_locked`

**Files:** Modify `src/autoagent/models/api.py`, `src/autoagent/devices/pool.py`; Test `tests/unit/test_device_pool.py`.

- [ ] **Step 1: Add the config field** — in `src/autoagent/models/api.py`, in `DefaultsConfig` (next to the other bool flags, e.g. after `self_update_enabled`):

```python
    # Auto-reconnect offline network (wifi) devices via `adb connect` on the
    # device-monitor loop (exponential backoff). Off by default — opt-in, like
    # every other auto-action here. Only touches network serials; skips
    # disabled / planned-reboot / in-use devices. No reboot.
    device_autoheal_enabled: bool = False
```

- [ ] **Step 2: Write the failing test** for `is_locked` — add to `tests/unit/test_device_pool.py` (read the file first for its imports / how it builds a `DevicePool`):

```python
@pytest.mark.asyncio
async def test_is_locked_reflects_the_per_serial_lock():
    from autoagent.devices.pool import DevicePool

    pool = DevicePool()
    assert pool.is_locked("dev1") is False
    async with pool.hold("dev1"):
        assert pool.is_locked("dev1") is True
    assert pool.is_locked("dev1") is False
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_device_pool.py -k is_locked`
Expected: FAIL — `DevicePool` has no attribute `is_locked`.

- [ ] **Step 4: Implement** — add to `src/autoagent/devices/pool.py` (as a method on `DevicePool`, near `available_count_sync`):

```python
    def is_locked(self, serial: str) -> bool:
        """True when this serial's per-serial lock is currently held (a sample
        is running on it or it's fenced by hold())."""
        lock = self._locks.get(serial)
        return lock is not None and lock.locked()
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_device_pool.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/models/api.py src/autoagent/devices/pool.py tests/unit/test_device_pool.py; echo "EXIT=$?"
git add src/autoagent/models/api.py src/autoagent/devices/pool.py tests/unit/test_device_pool.py
git commit -m "feat(devices): add device_autoheal_enabled config + DevicePool.is_locked"
```

---

## Task 2: `DeviceHealer`

**Files:** Create `src/autoagent/devices/healer.py`; Test `tests/unit/test_device_healer.py`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_device_healer.py`:

```python
from dataclasses import dataclass

import pytest

from autoagent.devices.healer import DeviceHealer


@dataclass
class _Dev:
    serial: str
    online: bool
    enabled: bool = True


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _healer(devs, *, enabled=True, is_locked=lambda s: False, clock=None):
    connected: list[str] = []
    clock = clock or _Clock()

    async def list_devices():
        return devs

    async def is_enabled():
        return enabled

    healer = DeviceHealer(
        list_devices=list_devices,
        is_locked=is_locked,
        is_enabled=is_enabled,
        connect=lambda s: connected.append(s),
        clock=clock,
    )
    return healer, connected, clock


@pytest.mark.asyncio
async def test_reconnects_offline_network_device_with_backoff():
    devs = [_Dev("10.0.0.5:5555", online=False)]
    healer, connected, clock = _healer(devs)
    await healer.maybe_heal()
    assert connected == ["10.0.0.5:5555"]  # first attempt
    # too soon → no second attempt
    clock.t += 5
    await healer.maybe_heal()
    assert connected == ["10.0.0.5:5555"]
    # past the 30s initial backoff → attempts again
    clock.t += 30
    await healer.maybe_heal()
    assert connected == ["10.0.0.5:5555", "10.0.0.5:5555"]


@pytest.mark.asyncio
async def test_online_resets_backoff():
    dev = _Dev("10.0.0.5:5555", online=False)
    healer, connected, clock = _healer([dev])
    await healer.maybe_heal()
    assert len(connected) == 1
    # comes back online → reset; then offline again → attempts immediately (not backed off)
    dev.online = True
    await healer.maybe_heal()
    dev.online = False
    await healer.maybe_heal()
    assert len(connected) == 2


@pytest.mark.asyncio
async def test_skips_usb_disabled_and_online():
    devs = [
        _Dev("emulator-5554", online=False),      # USB-ish, no host:port → skip
        _Dev("10.0.0.6:5555", online=False, enabled=False),  # disabled → skip
        _Dev("10.0.0.7:5555", online=True),       # online → skip
    ]
    healer, connected, _ = _healer(devs)
    await healer.maybe_heal()
    assert connected == []


@pytest.mark.asyncio
async def test_skips_locked_and_respects_disabled_toggle():
    devs = [_Dev("10.0.0.8:5555", online=False)]
    # locked → skip
    healer, connected, _ = _healer(devs, is_locked=lambda s: True)
    await healer.maybe_heal()
    assert connected == []
    # config off → skip
    healer2, connected2, _ = _healer([_Dev("10.0.0.9:5555", online=False)], enabled=False)
    await healer2.maybe_heal()
    assert connected2 == []


@pytest.mark.asyncio
async def test_connect_exception_is_isolated():
    devs = [_Dev("10.0.0.10:5555", online=False), _Dev("10.0.0.11:5555", online=False)]
    calls: list[str] = []

    def boom(serial):
        calls.append(serial)
        if serial.endswith("10:5555"):
            raise RuntimeError("adb down")

    async def list_devices():
        return devs

    async def is_enabled():
        return True

    healer = DeviceHealer(
        list_devices=list_devices, is_locked=lambda s: False,
        is_enabled=is_enabled, connect=boom, clock=_Clock(),
    )
    await healer.maybe_heal()  # must not raise
    assert set(calls) == {"10.0.0.10:5555", "10.0.0.11:5555"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_device_healer.py`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — create `src/autoagent/devices/healer.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_device_healer.py`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/devices/healer.py tests/unit/test_device_healer.py; echo "EXIT=$?"
git add src/autoagent/devices/healer.py tests/unit/test_device_healer.py
git commit -m "feat(devices): add DeviceHealer (auto-reconnect offline network devices)"
```

---

## Task 3: Monitor `on_tick` hook + wiring

**Files:** Modify `src/autoagent/devices/monitor.py`, `src/autoagent/api/_deps.py`; Test `tests/unit/test_device_monitor.py`.

- [ ] **Step 1: Write the failing test** — add to `tests/unit/test_device_monitor.py` (read it first for how it constructs a `DeviceMonitor` with stub callables):

```python
@pytest.mark.asyncio
async def test_sync_once_awaits_on_tick():
    from autoagent.devices.monitor import DeviceMonitor

    ticked = []

    async def _list():
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_device_monitor.py -k on_tick`
Expected: FAIL — `DeviceMonitor` got an unexpected keyword `on_tick`.

- [ ] **Step 3: Implement** — in `src/autoagent/devices/monitor.py`:
  - Add the param to `__init__` (after `on_state_change`): `on_tick: Callable[[], Awaitable[None]] | None = None`, and store `self._on_tick = on_tick`.
  - At the end of `sync_once` (right after `self._last_state = current`):

```python
        self._last_state = current
        if self._on_tick is not None:
            try:
                await self._on_tick()
            except Exception:  # noqa: BLE001
                log.exception("device monitor on_tick failed")
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_device_monitor.py`
Expected: PASS.

- [ ] **Step 5: Wire the healer** in `src/autoagent/api/_deps.py::get_device_monitor` — after the `on_device_state_change` import and before constructing `DeviceMonitor`, build the healer:

```python
        from autoagent.devices.healer import DeviceHealer
        from autoagent.models.api import DefaultsConfig
        from autoagent.storage.configs import get_config

        async def _autoheal_enabled() -> bool:
            cfg = await get_config("defaults")
            return DefaultsConfig.model_validate(cfg).device_autoheal_enabled if cfg else False

        _healer = DeviceHealer(
            list_devices=list_stored_devices,
            is_locked=pool.is_locked,
            is_enabled=_autoheal_enabled,
        )
```

  Then add `on_tick=_healer.maybe_heal,` to the `DeviceMonitor(...)` constructor call.

- [ ] **Step 6: Confirm import + run**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run python -c "import autoagent.main" && uv run pytest -q tests/unit/test_device_monitor.py tests/unit/test_device_healer.py tests/unit/test_device_pool.py`
Expected: import OK + PASS.

- [ ] **Step 7: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/devices/monitor.py src/autoagent/api/_deps.py tests/unit/test_device_monitor.py; echo "EXIT=$?"
git add src/autoagent/devices/monitor.py src/autoagent/api/_deps.py tests/unit/test_device_monitor.py
git commit -m "feat(devices): run the healer on each device-monitor tick"
```

---

## Task 4: Config-page toggle

**Files:** Modify `web/src/types/api.ts`, `web/src/pages/Config.tsx`.

- [ ] **Step 1: Add the TS field** — in `web/src/types/api.ts`, in `GlobalDefaults` (next to `self_update_enabled`):

```ts
  device_autoheal_enabled?: boolean
```

- [ ] **Step 2: Add the Switch** — in `web/src/pages/Config.tsx`, in the defaults form near the `self_update_enabled` Switch `Form.Item`, add:

```tsx
<Form.Item
  name="device_autoheal_enabled"
  label="设备自动重连"
  valuePropName="checked"
  extra="开启后，离线的网络(wifi)设备会在设备监控轮询里自动 adb connect 重连(指数退避)。只对网络设备生效，跳过 USB/已禁用/初始化中/占用中的设备，不 reboot。默认关。"
>
  <Switch />
</Form.Item>
```

Read `Config.tsx` first to place it consistently inside the defaults `Card`/form and confirm `Switch`/`Form.Item` are already imported (they are — used by `verbose_logs`/`self_update_enabled`).

- [ ] **Step 3: Typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`
Expected: clean.

- [ ] **Step 4: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/Config.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/types/api.ts web/src/pages/Config.tsx
git commit -m "feat(web): add the device auto-reconnect toggle to Config"
```

---

## Task 5: Full verification + docs

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1: Backend fast suite + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run ruff check . && uv run pytest -q -m "not playwright and not android and not slow"`
Expected: lint clean, all pass.

- [ ] **Step 2: Frontend full suite + typecheck + lint + build**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run && pnpm build`
Expected: all green.

- [ ] **Step 3: CLAUDE.md changelog entry** — document device auto-heal (opt-in `device_autoheal_enabled`, `DeviceHealer` on the monitor tick, network-only `adb connect` with backoff, exclusions, reuses existing offline/online DingTalk transitions, no reboot). Reference the spec + this plan.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the device auto-heal feature"
```

- [ ] **Step 5: Push + verify CI** — user pre-authorized. Push and confirm CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`. If the frontend job dies with no log (the known transient recharts-era runner kill), re-run the failed job once before treating it as a real failure.

---

## Self-Review

**1. Spec coverage:**
- `device_autoheal_enabled` opt-in default off → Task 1. ✓
- Network-only (`_is_network_serial`) → Task 2 (`maybe_heal`). ✓
- Exclusions: enabled=False / `is_expected_reboot` / pool-locked → Task 2 (checks) + Task 1 (`is_locked`). ✓
- `DeviceHealer` w/ backoff, exception isolation, config-off → Task 2. ✓
- Monitor `on_tick` wiring → Task 3. ✓
- Reuses existing offline/online DingTalk transitions (no new alert) → nothing to add; the healer only logs. ✓
- Config-page toggle + TS type → Task 4. ✓
- Testing (healer units incl. USB/disabled/locked/off/exception, is_locked, monitor on_tick) → Tasks 1-3 + Task 5. ✓

**2. Placeholder scan:** No TBD/TODO. "Read the file first" notes (Task 1/3/4 tests, Config placement) name the exact file + what to mirror.

**3. Type consistency:** `DeviceHealer(list_devices, is_locked, is_enabled, connect, clock)` matches Task 2 def, the test harness, and the Task 3 wiring (`list_stored_devices`/`pool.is_locked`/`_autoheal_enabled`). `is_locked(serial) -> bool` matches Task 1 def + Task 2 usage + Task 3 injection. `DeviceMonitor(..., on_tick=)` matches Task 3 def + the `_deps` call. `device_autoheal_enabled` consistent across `DefaultsConfig` (Task 1), `_autoheal_enabled` reader (Task 3), `GlobalDefaults` TS (Task 4), and the Config Switch `name` (Task 4). `DeviceInfo.online/.enabled/.serial` are the row attrs `maybe_heal` reads (Task 2), matching the `_Dev` test stub and the real `list_stored_devices` rows.
