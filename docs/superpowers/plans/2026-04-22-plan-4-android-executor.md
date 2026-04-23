# Plan 4 — Android Executor (uiautomator2 + OCR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mode=gui_android` execution so the existing batch/quick-test/frontend flow can run against Android emulator/real devices, first with a Tier 1 `ui_tree_only` path and then with Tier 2 OCR + long-response stitching.

**Architecture:** Device discovery and scheduling stay server-side: an application-scoped `DeviceMonitor` syncs `adb devices -l` into a persistent `devices` table, and a singleton `DevicePool` gates sample execution with per-serial locks. `AndroidExecutor` reuses the existing executor/result pipeline, but extends `ExecutorContext` so screenshots, action logs, replay files, and device metadata flow into `SampleResult.metadata`. Tier 2 is an additive extension on top of Tier 1: `ResponseExtractor` grows OCR strategies, `ScrollStitcher` captures long responses, and `CompleteDetector` gains `pixel_stable` without revisiting Tier 1 behavior.

**Tech Stack:** Python 3.11 · FastAPI · SQLAlchemy asyncio + SQLite · `uiautomator2` · `adb` CLI · pytest (`android` and `slow` markers) · React 18 + TanStack Query v5 + Ant Design · RapidOCR ONNXRuntime (Tier 2).

**Spec reference:** `docs/superpowers/specs/2026-04-22-plan-4-android-executor-design.md`.

**Prereq:** Plan 3 complete at tag `web-gui-executor-v0.3.0`; `adb` is on `PATH`; at least one Android emulator or USB/Wi-Fi device is available for `@pytest.mark.android` and manual smoke.

**Delivery tags:** Tier 1 ships at `android-executor-tier1-v0.4.0`; Tier 2 ships at `android-executor-v0.4.0`.

---

## File Structure

```text
src/autoagent/
  devices/
    __init__.py
    adb.py
    pool.py
    monitor.py
  executors/
    android_executor.py
    android_input.py
    android_action_runner.py
    android_locator.py
    response_extractor.py
    ocr.py
    scroll_stitcher.py
    complete_detector.py
    screenshot_store.py
    action_runner.py
    base.py
  api/
    _deps.py
    batches.py
    devices.py
    tests.py
  storage/
    devices.py
    database.py
  models/
    api.py
    db.py
  profiles/
    schemas.py
  utils/
    env_expand.py
  main.py

tests/
  fixtures/
    fake_chat_apk/
    android_ui_samples/
    android_screenshots/
  unit/
    test_device_storage.py
    test_adb_wrapper.py
    test_device_pool.py
    test_device_monitor.py
    test_android_locator.py
    test_android_input.py
    test_android_action_runner.py
    test_response_extractor_ui_tree.py
    test_response_extractor_ocr.py
    test_scroll_stitcher.py
    test_complete_detector_android.py
    test_android_executor_unit.py
    test_scheduler_device_pool.py
    test_executor_factory.py
  integration/
    test_devices_endpoint.py
    test_tests_sync_android.py
    test_android_executor_e2e.py

web/src/
  api/
    devices.ts
    profiles.ts
    batches.ts
  hooks/
    useBatchStream.ts
  pages/
    Devices/Index.tsx
    Devices/Index.test.tsx
    Batches/New.tsx
    Batches/SampleDetail.tsx
    Batches/SampleDetail.test.tsx
    Profiles/Edit.tsx
    Profiles/ConnectivityTestModal.tsx
    Profiles/Edit.test.tsx
    Tests/Quick.tsx
  components/
    AppLayout.tsx
    ScreenshotStrip.tsx
  App.tsx
  types/api.ts
```

## Tier 1 — Real device minimum viable loop

### Task 1: Add Android deps, pytest markers, and operator docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [x] **Step 1: Write the failing baseline checks**

Add marker-aware commands to the plan and verify the repo does not yet know about Android-specific markers or dependencies.

Run:
```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
python3.11 - <<'PY'
import importlib
for name in ("uiautomator2",):
    importlib.import_module(name)
print("ok")
PY
```
Expected: pytest is green, but the import step fails with `ModuleNotFoundError: No module named 'uiautomator2'`.

- [x] **Step 2: Add deps and markers to `pyproject.toml`**

Extend the dependency and pytest marker lists:

```toml
dependencies = [
  # ...
  "uiautomator2>=3.2,<4.0",
]

[tool.pytest.ini_options]
markers = [
  "playwright: requires real Chromium via `python3.11 -m playwright install chromium`",
  "android: requires adb + emulator/real device",
  "slow: slower OCR and image-processing coverage",
]
```

- [x] **Step 3: Document the Android operator prerequisites**

Add a README section immediately after the Playwright prerequisite:

```md
### Android executor prerequisite (Plan 4 Tier 1)

Android mode requires:

    brew install android-platform-tools   # macOS
    python3.11 -m pip install -e '.[dev]'
    adb devices

Tier 1 uses `uiautomator2` plus a connected emulator/real device. If you plan to use `input_method: adb_keyboard`, install `com.android.adbkeyboard` on the device manually; we do not bundle that APK in this repo.
```

In `CLAUDE.md`, extend the common commands block and environment notes:

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
python3.11 -m pytest -v -m android
adb devices -l
```

```md
- **Android verification:** real-device tests are marked `@pytest.mark.android` and are skipped in the fast suite.
- **ADB Keyboard:** `input_method: adb_keyboard` expects `com.android.adbkeyboard` to be preinstalled; Plan 4 does not auto-install it.
```

- [x] **Step 4: Reinstall deps and verify the baseline remains green**

Run:
```bash
python3.11 -m pip install -e '.[dev]'
python3.11 -m pytest -q -m "not playwright and not android and not slow"
python3.11 -m ruff check .
python3.11 -m ruff format --check .
```
Expected: install exits 0; pytest/ruff all pass.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml README.md CLAUDE.md
git commit -m "chore(android): add uiautomator2 deps and markers"
```

---

### Task 2: Add persistent device storage and API schemas

**Files:**
- Modify: `src/autoagent/models/db.py`
- Modify: `src/autoagent/models/api.py`
- Create: `src/autoagent/storage/devices.py`
- Create: `tests/unit/test_device_storage.py`

- [x] **Step 1: Write the failing storage test**

`tests/unit/test_device_storage.py`:

```python
from datetime import datetime, timezone

import pytest

from autoagent.storage.database import init_db
from autoagent.storage.devices import (
    list_devices,
    upsert_discovered_device,
    update_device_enabled,
    update_device_label,
)


@pytest.mark.asyncio
async def test_upsert_and_patch_device() -> None:
    await init_db()
    await upsert_discovered_device(
        serial="emulator-5554",
        model="sdk_gphone64_arm64",
        android_version="14",
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
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_device_storage.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'autoagent.storage.devices'`.

- [x] **Step 3: Implement the ORM model and storage helpers**

In `src/autoagent/models/db.py`, add:

```python
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class Device(Base):
    __tablename__ = "devices"
    serial = Column(String, primary_key=True)
    label = Column(String, nullable=True)
    model = Column(String, nullable=True)
    android_version = Column(String, nullable=True)
    online = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
```

In `src/autoagent/models/api.py`, add the shared schemas:

```python
class DeviceInfo(BaseModel):
    serial: str
    label: str | None = None
    model: str | None = None
    android_version: str | None = None
    online: bool
    enabled: bool
    last_seen_at: datetime | None = None


class DeviceLabelUpdate(BaseModel):
    label: str | None = None
```

Create `src/autoagent/storage/devices.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select

from autoagent.models.api import DeviceInfo
from autoagent.models.db import Device
from autoagent.storage.database import get_sessionmaker


def _to_info(row: Device) -> DeviceInfo:
    return DeviceInfo(
        serial=row.serial,
        label=row.label,
        model=row.model,
        android_version=row.android_version,
        online=row.online,
        enabled=row.enabled,
        last_seen_at=row.last_seen_at,
    )


async def upsert_discovered_device(
    *, serial: str, model: str | None, android_version: str | None, online: bool, seen_at: datetime
) -> DeviceInfo:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(Device, serial) or Device(serial=serial)
        s.add(row)
        row.model = model
        row.android_version = android_version
        row.online = online
        row.last_seen_at = seen_at
        if row.enabled is None:
            row.enabled = True
        await s.commit()
        await s.refresh(row)
        return _to_info(row)


async def list_devices() -> list[DeviceInfo]:
    sm = get_sessionmaker()
    async with sm() as s:
        rows = await s.execute(
            select(Device).order_by(desc(Device.online), desc(Device.last_seen_at))
        )
        return [_to_info(row) for row in rows.scalars().all()]


async def update_device_enabled(serial: str, *, enabled: bool) -> DeviceInfo | None:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(Device, serial)
        if row is None:
            return None
        row.enabled = enabled
        await s.commit()
        await s.refresh(row)
        return _to_info(row)


async def update_device_label(serial: str, label: str | None) -> DeviceInfo | None:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(Device, serial)
        if row is None:
            return None
        row.label = label
        await s.commit()
        await s.refresh(row)
        return _to_info(row)


async def mark_missing_devices_offline(seen_serials: set[str]) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        rows = await s.execute(select(Device))
        for row in rows.scalars().all():
            if row.serial not in seen_serials:
                row.online = False
        await s.commit()
```

- [x] **Step 4: Run the focused test**

Run:
```bash
python3.11 -m pytest tests/unit/test_device_storage.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/models/db.py src/autoagent/models/api.py src/autoagent/storage/devices.py tests/unit/test_device_storage.py
git commit -m "feat(devices): add persistent device storage"
```

---

### Task 3: Implement the `adb` wrapper and parser

**Files:**
- Create: `src/autoagent/devices/__init__.py`
- Create: `src/autoagent/devices/adb.py`
- Create: `tests/unit/test_adb_wrapper.py`

- [x] **Step 1: Write the failing parser tests**

`tests/unit/test_adb_wrapper.py`:

```python
from unittest.mock import MagicMock

import pytest

from autoagent.devices.adb import AdbCommandError, list_devices


def test_list_devices_parses_adb_devices_l(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = (
        "List of devices attached\n"
        "emulator-5554 device product:sdk model:sdk_gphone64_arm64 device:emu transport_id:1\n"
        "R3CN30 offline usb:1-1 transport_id:2\n"
    )
    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", lambda *a, **k: proc)

    rows = list_devices()

    assert len(rows) == 2
    assert rows[0].serial == "emulator-5554"
    assert rows[0].online is True
    assert rows[0].model == "sdk_gphone64_arm64"
    assert rows[1].serial == "R3CN30"
    assert rows[1].online is False


def test_list_devices_raises_on_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock(returncode=1, stdout="", stderr="adb missing")
    monkeypatch.setattr("autoagent.devices.adb.subprocess.run", lambda *a, **k: proc)
    with pytest.raises(AdbCommandError):
        list_devices()
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_adb_wrapper.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'autoagent.devices'`.

- [x] **Step 3: Implement `src/autoagent/devices/adb.py`**

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass


class AdbCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    online: bool
    model: str | None = None
    android_version: str | None = None


def _run_adb(*args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AdbCommandError(proc.stderr.strip() or f"adb {' '.join(args)} failed")
    return proc


def list_devices() -> list[AdbDevice]:
    proc = _run_adb("devices", "-l")
    rows: list[AdbDevice] = []
    for line in proc.stdout.splitlines():
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        serial, state, *extras = parts
        kv = {
            item.split(":", 1)[0]: item.split(":", 1)[1]
            for item in extras
            if ":" in item
        }
        rows.append(
            AdbDevice(
                serial=serial,
                online=state == "device",
                model=kv.get("model"),
                android_version=None,
            )
        )
    return rows


def connect(target: str) -> None:
    _run_adb("connect", target)


def disconnect(target: str) -> None:
    _run_adb("disconnect", target)
```

- [x] **Step 4: Run the focused test**

Run:
```bash
python3.11 -m pytest tests/unit/test_adb_wrapper.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/devices/__init__.py src/autoagent/devices/adb.py tests/unit/test_adb_wrapper.py
git commit -m "feat(devices): add adb wrapper"
```

---

### Task 4: Add `DevicePool` locking and acquisition semantics

**Files:**
- Create: `src/autoagent/devices/pool.py`
- Create: `tests/unit/test_device_pool.py`

- [x] **Step 1: Write the failing pool tests**

`tests/unit/test_device_pool.py`:

```python
import asyncio

import pytest

from autoagent.devices.pool import DeviceBusy, DeviceDisabled, DevicePool
from autoagent.models.api import DeviceInfo


def _device(serial: str, *, online: bool = True, enabled: bool = True) -> DeviceInfo:
    return DeviceInfo(serial=serial, online=online, enabled=enabled)


@pytest.mark.asyncio
async def test_acquire_prefers_requested_serial() -> None:
    pool = DevicePool(lambda: [_device("a"), _device("b")])
    async with pool.acquire(preferred="b", timeout_sec=0.1) as serial:
        assert serial == "b"


@pytest.mark.asyncio
async def test_acquire_raises_when_device_disabled_mid_wait() -> None:
    devices = [_device("a", enabled=True)]
    pool = DevicePool(lambda: devices)

    async with pool.acquire(preferred="a", timeout_sec=0.1):
        async def waiter():
            async with pool.acquire(preferred="a", timeout_sec=0.2):
                return None

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        devices[0] = _device("a", enabled=False)
        with pytest.raises(DeviceDisabled):
            await task
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_device_pool.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'autoagent.devices.pool'`.

- [x] **Step 3: Implement `DevicePool`**

`src/autoagent/devices/pool.py`:

```python
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
        return sum(
            1
            for device in self._list_devices()
            if device.online and device.enabled and not self._locks.get(device.serial, asyncio.Lock()).locked()
        )

    @asynccontextmanager
    async def acquire(self, preferred: str | None, timeout_sec: float = 60):
        deadline = time.monotonic() + timeout_sec
        while True:
            candidates = [d for d in self._list_devices() if d.online and d.enabled]
            if preferred:
                candidates = [d for d in candidates if d.serial == preferred]
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
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_device_pool.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/devices/pool.py tests/unit/test_device_pool.py
git commit -m "feat(devices): add device pool locking"
```

---

### Task 5: Add `DeviceMonitor` and application-scoped lifecycle wiring

**Files:**
- Create: `src/autoagent/devices/monitor.py`
- Modify: `src/autoagent/api/_deps.py`
- Modify: `src/autoagent/main.py`
- Create: `tests/unit/test_device_monitor.py`

- [x] **Step 1: Write the failing monitor test**

`tests/unit/test_device_monitor.py`:

```python
from datetime import datetime, timezone

import pytest

from autoagent.devices.monitor import DeviceMonitor


@pytest.mark.asyncio
async def test_sync_once_upserts_and_marks_missing_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = [
        [("emulator-5554", True, "sdk", "14")],
        [],
    ]

    async def fake_upsert(*, serial, model, android_version, online, seen_at):
        events.append((serial, online, model, android_version, isinstance(seen_at, datetime)))

    async def fake_mark_missing_online(now_seen):
        gone.append(sorted(now_seen))

    events: list[tuple] = []
    gone: list[list[str]] = []

    monitor = DeviceMonitor(
        list_devices=lambda: [
            type("D", (), dict(serial=s, online=o, model=m, android_version=v))()
            for s, o, m, v in seen.pop(0)
        ],
        upsert_device=fake_upsert,
        mark_missing_offline=fake_mark_missing_online,
        interval_sec=0.01,
    )

    await monitor.sync_once()
    await monitor.sync_once()

    assert events[0][:4] == ("emulator-5554", True, "sdk", "14")
    assert gone[-1] == []
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_device_monitor.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'autoagent.devices.monitor'`.

- [x] **Step 3: Implement `DeviceMonitor` and singleton getters**

Create `src/autoagent/devices/monitor.py`:

```python
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


class DeviceMonitor:
    def __init__(self, *, list_devices, upsert_device, mark_missing_offline, interval_sec: float = 5.0):
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
            except Exception:
                log.exception("device monitor sync failed")
            await asyncio.sleep(self._interval_sec)
```

In `src/autoagent/api/_deps.py`, add device singletons:

```python
from autoagent.devices.adb import list_devices as adb_list_devices
from autoagent.devices.monitor import DeviceMonitor
from autoagent.devices.pool import DevicePool
from autoagent.storage.devices import list_devices, mark_missing_devices_offline, upsert_discovered_device

_device_pool: DevicePool | None = None
_device_monitor: DeviceMonitor | None = None


def get_device_pool() -> DevicePool:
    global _device_pool
    if _device_pool is None:
        _device_pool = DevicePool()
    return _device_pool


def get_device_monitor() -> DeviceMonitor:
    global _device_monitor
    if _device_monitor is None:
        pool = get_device_pool()

        async def _upsert_and_refresh(**kwargs):
            await upsert_discovered_device(**kwargs)
            pool.update_snapshot(await list_devices())

        async def _mark_missing_and_refresh(seen_serials: set[str]) -> None:
            await mark_missing_devices_offline(seen_serials)
            pool.update_snapshot(await list_devices())

        _device_monitor = DeviceMonitor(
            list_devices=adb_list_devices,
            upsert_device=_upsert_and_refresh,
            mark_missing_offline=_mark_missing_and_refresh,
        )
    return _device_monitor
```

In `src/autoagent/main.py`, start and stop the monitor inside `lifespan`:

```python
from contextlib import asynccontextmanager, suppress

from autoagent.api._deps import get_device_monitor

    monitor_task = asyncio.create_task(get_device_monitor().run())
    try:
        yield
    finally:
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_device_monitor.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/devices/monitor.py src/autoagent/api/_deps.py src/autoagent/main.py tests/unit/test_device_monitor.py
git commit -m "feat(devices): add background device monitor"
```

---

### Task 6: Fill in the `/devices` API

**Files:**
- Modify: `src/autoagent/api/devices.py`
- Create: `tests/integration/test_devices_endpoint.py`

- [x] **Step 1: Write the failing endpoint tests**

`tests/integration/test_devices_endpoint.py`:

```python
import pytest

from autoagent.models.api import DeviceInfo
from tests.integration.test_config_endpoints import _h


async def test_refresh_returns_devices(client, monkeypatch):
    from autoagent.api import devices as mod

    async def fake_refresh():
        return [DeviceInfo(serial="emulator-5554", online=True, enabled=True)]

    monkeypatch.setattr(mod, "refresh_devices_now", fake_refresh)
    h = await _h(client)
    r = await client.post("/api/v1/devices/refresh", headers=h)
    assert r.status_code == 200
    assert r.json()[0]["serial"] == "emulator-5554"


async def test_patch_label_404(client):
    h = await _h(client)
    r = await client.patch("/api/v1/devices/missing", json={"label": "x"}, headers=h)
    assert r.status_code == 404
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/integration/test_devices_endpoint.py -v
```
Expected: FAIL with `404` on `/devices/refresh` and `405` on `PATCH /devices/{serial}`.

- [x] **Step 3: Implement the endpoints**

Replace `src/autoagent/api/devices.py` with:

```python
from fastapi import APIRouter, Depends, HTTPException

from autoagent.api._deps import get_device_monitor
from autoagent.auth.deps import require_user
from autoagent.devices.adb import AdbCommandError
from autoagent.models.api import DeviceInfo, DeviceLabelUpdate
from autoagent.storage.devices import (
    list_devices,
    update_device_enabled,
    update_device_label,
)

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(require_user)])


async def refresh_devices_now() -> list[DeviceInfo]:
    monitor = get_device_monitor()
    await monitor.sync_once()
    return await list_devices()


@router.get("", response_model=list[DeviceInfo])
async def list_devices_route() -> list[DeviceInfo]:
    return await list_devices()


@router.post("/refresh", response_model=list[DeviceInfo])
async def refresh_devices_route() -> list[DeviceInfo]:
    try:
        return await refresh_devices_now()
    except AdbCommandError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/{serial}/connect", response_model=DeviceInfo)
async def connect(serial: str) -> DeviceInfo:
    row = await update_device_enabled(serial, enabled=True)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


@router.post("/{serial}/disconnect", response_model=DeviceInfo)
async def disconnect(serial: str) -> DeviceInfo:
    row = await update_device_enabled(serial, enabled=False)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row


@router.patch("/{serial}", response_model=DeviceInfo)
async def patch_label(serial: str, body: DeviceLabelUpdate) -> DeviceInfo:
    row = await update_device_label(serial, body.label)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row
```

- [x] **Step 4: Run the integration tests**

Run:
```bash
python3.11 -m pytest tests/integration/test_devices_endpoint.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/api/devices.py tests/integration/test_devices_endpoint.py
git commit -m "feat(devices): implement devices endpoints"
```

---

### Task 7: Refactor shared executor plumbing for Android metadata

**Files:**
- Modify: `src/autoagent/executors/base.py`
- Modify: `src/autoagent/executors/action_runner.py`
- Modify: `src/autoagent/executors/screenshot_store.py`
- Create: `src/autoagent/utils/env_expand.py`
- Modify: `tests/unit/test_action_runner.py`
- Modify: `tests/unit/test_screenshot_store.py`

- [x] **Step 1: Write the failing metadata/plumbing tests**

Add to `tests/unit/test_screenshot_store.py`:

```python
from pathlib import Path

from autoagent.executors.screenshot_store import ScreenshotResult


def test_result_metadata_round_trip(tmp_path: Path) -> None:
    result = ScreenshotResult(
        path=tmp_path / "01_ready.png",
        label="ready",
        is_sensitive=True,
        error=None,
    )
    payload = result.to_metadata()
    assert payload["name"] == "01_ready.png"
    assert payload["label"] == "ready"
    assert payload["is_sensitive"] is True
```

Add to `tests/unit/test_action_runner.py`:

```python
from autoagent.utils.env_expand import expand_env_value


def test_expand_env_value_reads_shell(monkeypatch):
    monkeypatch.setenv("CHAT_TOKEN", "abc")
    assert expand_env_value("$CHAT_TOKEN") == "abc"
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_action_runner.py tests/unit/test_screenshot_store.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'autoagent.utils.env_expand'` and missing `ScreenshotResult`.

- [x] **Step 3: Implement the shared abstractions**

Create `src/autoagent/utils/env_expand.py`:

```python
from __future__ import annotations

import os
import re

ENV_VAR_RE = re.compile(r"^\$([A-Z_][A-Z0-9_]*)$")


def expand_env_value(text: str) -> str:
    match = ENV_VAR_RE.match(text)
    if not match:
        return text
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"environment variable {name} is not set")
    return value
```

In `src/autoagent/executors/base.py`, extend `ExecutorContext` and merge executor metadata into `SampleResult.metadata`:

```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecutorContext:
    logs_dir: str | None = None
    verbose_logs: bool = True
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    action_log: list[dict[str, Any]] = field(default_factory=list)
    action_replay_path: Path | None = None
    screenshot_index: list[Any] = field(default_factory=list)
    device_serial: str | None = None


def _merge_ctx_metadata(sample: Sample, ctx: ExecutorContext) -> dict[str, Any]:
    metadata = dict(sample.metadata)
    if ctx.action_log:
        metadata["action_log"] = ctx.action_log
    if ctx.action_replay_path is not None:
        metadata["action_replay_available"] = True
    if ctx.device_serial:
        metadata["device_serial"] = ctx.device_serial
    if ctx.screenshot_index:
        metadata["screenshots"] = [item.to_metadata() for item in ctx.screenshot_index]
    return metadata
```

In `src/autoagent/executors/screenshot_store.py`, add:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenshotResult:
    path: Path
    label: str
    is_sensitive: bool = False
    error: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "name": self.path.name,
            "label": self.label,
            "is_sensitive": self.is_sensitive,
            "error": self.error,
        }
```

In `src/autoagent/executors/action_runner.py`, keep the existing web behavior but import `expand_env_value` instead of duplicating regex logic.

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_action_runner.py tests/unit/test_screenshot_store.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/executors/base.py src/autoagent/executors/action_runner.py src/autoagent/executors/screenshot_store.py src/autoagent/utils/env_expand.py tests/unit/test_action_runner.py tests/unit/test_screenshot_store.py
git commit -m "refactor(executors): add shared android metadata plumbing"
```

---

### Task 8: Extend Android profile schema, locator helpers, and input control

**Files:**
- Modify: `src/autoagent/profiles/schemas.py`
- Create: `src/autoagent/executors/android_locator.py`
- Create: `src/autoagent/executors/android_input.py`
- Create: `tests/unit/test_android_locator.py`
- Create: `tests/unit/test_android_input.py`
- Modify: `tests/unit/test_profiles.py`

- [x] **Step 1: Write the failing tests**

`tests/unit/test_android_locator.py`:

```python
from autoagent.executors.android_locator import selector_kwargs
from autoagent.profiles.schemas import Locator


def test_selector_kwargs_maps_resource_id() -> None:
    assert selector_kwargs(Locator(type="resource_id", value="com.demo:id/input")) == {
        "resourceId": "com.demo:id/input"
    }
```

`tests/unit/test_android_input.py`:

```python
import pytest

from autoagent.executors.android_input import resolve_input_method


def test_auto_uses_adb_keyboard_for_non_ascii() -> None:
    assert resolve_input_method("auto", "你好") == "adb_keyboard"
```

Extend `tests/unit/test_profiles.py::test_parse_android_profile` to assert:

```python
assert p.input_method == "auto"
assert p.serial is None
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_profiles.py tests/unit/test_android_locator.py tests/unit/test_android_input.py -v
```
Expected: FAIL because the new modules and `AndroidProfile` fields do not exist yet.

- [x] **Step 3: Implement schema + locator + input helpers**

In `src/autoagent/profiles/schemas.py`, extend `AndroidProfile`:

```python
class AndroidProfile(BaseModel):
    name: str
    platform: Literal["android"]
    package: str
    activity: str | None = None
    serial: str | None = None
    input_method: Literal["auto", "adb_keyboard", "u2_send_keys"] = "auto"
    ready_check: AndroidReadyCheckTree
    recovery_path: list[ActionStep]
    input_locator: Locator
    send_button_locator: Locator
    response_extraction: AndroidResponseExtraction
    new_session_action: list[ActionStep] = Field(default_factory=list)
    complete_detection: CompleteDetection
```

Create `src/autoagent/executors/android_locator.py`:

```python
from __future__ import annotations

from autoagent.profiles.schemas import Locator


def selector_kwargs(locator: Locator) -> dict[str, str]:
    if locator.type == "resource_id":
        return {"resourceId": locator.value}
    if locator.type == "text":
        return {"text": locator.value}
    if locator.type == "xpath":
        return {"xpath": locator.value}
    if locator.type == "class":
        return {"className": locator.value}
    raise ValueError(f"unsupported direct selector type: {locator.type}")
```

Create `src/autoagent/executors/android_input.py`:

```python
from __future__ import annotations

import base64


class AdbKeyboardNotInstalled(RuntimeError):
    pass


def resolve_input_method(configured: str, prompt: str) -> str:
    if configured != "auto":
        return configured
    return "adb_keyboard" if any(ord(ch) > 127 for ch in prompt) else "u2_send_keys"
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_profiles.py tests/unit/test_android_locator.py tests/unit/test_android_input.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/profiles/schemas.py src/autoagent/executors/android_locator.py src/autoagent/executors/android_input.py tests/unit/test_android_locator.py tests/unit/test_android_input.py tests/unit/test_profiles.py
git commit -m "feat(android): add profile schema, locator, and input helpers"
```

---

### Task 9: Implement `AndroidActionRunner`

**Files:**
- Create: `src/autoagent/executors/android_action_runner.py`
- Create: `tests/unit/test_android_action_runner.py`

- [x] **Step 1: Write the failing action-runner tests**

`tests/unit/test_android_action_runner.py`:

```python
from unittest.mock import MagicMock

import pytest

from autoagent.executors.android_action_runner import AndroidActionRunner
from autoagent.profiles.schemas import ActionStep, Locator


@pytest.mark.asyncio
async def test_click_locator_dispatches_to_u2() -> None:
    device = MagicMock()
    target = MagicMock()
    target.click.return_value = None
    device.return_value = target

    runner = AndroidActionRunner(device=device, input_controller=MagicMock(), action_log=[])
    await runner.run(
        [ActionStep(action="click_locator", locator=Locator(type="text", value="发送"))]
    )

    target.click.assert_called_once()
    assert runner.log[0]["action"] == "click_locator"
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_android_action_runner.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'autoagent.executors.android_action_runner'`.

- [x] **Step 3: Implement the runner**

Create `src/autoagent/executors/android_action_runner.py`:

```python
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from autoagent.executors.android_locator import selector_kwargs
from autoagent.profiles.schemas import ActionStep, Locator


class AndroidActionRunner:
    def __init__(
        self,
        *,
        device: Any,
        input_controller: Any,
        action_log: list[dict[str, Any]],
        replay_path: Path | None = None,
    ) -> None:
        self.device = device
        self.input_controller = input_controller
        self.log = action_log
        self._replay_path = replay_path
        self._t0 = time.monotonic()

    async def run(self, steps: list[ActionStep]) -> None:
        for step in steps:
            entry = {"t_ms": int((time.monotonic() - self._t0) * 1000), "action": step.action}
            try:
                await self._dispatch(step)
                entry["ok"] = True
            except Exception as e:
                entry["ok"] = False
                entry["error"] = f"{type(e).__name__}: {e}"
                self.log.append(entry)
                raise
            self.log.append(entry)

    async def _dispatch(self, step: ActionStep) -> None:
        if step.action == "click_locator":
            self.device(**selector_kwargs(step.locator)).click()
        elif step.action == "input":
            await self.input_controller.set_text(step.locator, step.text)
        elif step.action == "wait_for":
            await asyncio.to_thread(self.device(**selector_kwargs(step.locator)).wait, timeout=getattr(step, "timeout_sec", 5))
        elif step.action == "launch_app":
            await asyncio.to_thread(self.device.app_start, step.package, getattr(step, "activity", None), True)
        elif step.action == "kill_app":
            await asyncio.to_thread(self.device.app_stop, step.package)
        elif step.action == "press_key":
            await asyncio.to_thread(self.device.press, step.key)
        elif step.action == "swipe":
            await asyncio.to_thread(self.device.swipe, step.x1, step.y1, step.x2, step.y2, getattr(step, "duration_sec", 0.1))
        elif step.action == "tap_xy":
            await asyncio.to_thread(self.device.click, step.x, step.y)
        else:
            raise ValueError(f"unknown android action: {step.action}")
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_android_action_runner.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/executors/android_action_runner.py tests/unit/test_android_action_runner.py
git commit -m "feat(android): add android action runner"
```

---

### Task 10: Add Tier 1 response extraction and Android completion detection

**Files:**
- Create: `src/autoagent/executors/response_extractor.py`
- Modify: `src/autoagent/executors/complete_detector.py`
- Create: `tests/unit/test_response_extractor_ui_tree.py`
- Create: `tests/unit/test_complete_detector_android.py`

- [x] **Step 1: Write the failing tests**

`tests/unit/test_response_extractor_ui_tree.py`:

```python
from autoagent.executors.response_extractor import UiTreeExtractor


def test_ui_tree_extractor_returns_latest_bubble() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.ListView">
        <node class="android.widget.LinearLayout">
          <node class="android.widget.TextView" text="old" />
        </node>
        <node class="android.widget.LinearLayout">
          <node class="android.widget.TextView" text="new" />
        </node>
      </node>
    </hierarchy>
    """
    result = UiTreeExtractor().extract_from_xml(xml, bubble_class="android.widget.TextView")
    assert result.text == "new"
    assert result.method_used == "ui_tree"
```

`tests/unit/test_complete_detector_android.py`:

```python
import pytest

from autoagent.executors.complete_detector import wait_for_ui_tree_stable


@pytest.mark.asyncio
async def test_wait_for_ui_tree_stable_returns_after_same_xml(monkeypatch):
    seq = iter(["<a/>", "<a/>", "<a/>"])

    class Device:
        def dump_hierarchy(self, compressed=False):
            return next(seq)

    await wait_for_ui_tree_stable(Device(), stable_sec=0.0, max_wait_sec=0.2)
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_response_extractor_ui_tree.py tests/unit/test_complete_detector_android.py -v
```
Expected: FAIL with missing extractor module and missing `wait_for_ui_tree_stable`.

- [x] **Step 3: Implement Tier 1 extractor + detector**

Create `src/autoagent/executors/response_extractor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass
class ExtractionResult:
    text: str
    method_used: str
    ocr_lines: list[str] | None = None
    ui_tree_node_count: int | None = None
    frames: int = 1
    stitched: bool = False


class UiTreeExtractor:
    def extract_from_xml(self, xml: str, *, bubble_class: str) -> ExtractionResult:
        root = ET.fromstring(xml)
        matches = [node for node in root.iter("node") if node.attrib.get("class") == bubble_class]
        text = matches[-1].attrib.get("text", "") if matches else ""
        return ExtractionResult(text=text, method_used="ui_tree", ui_tree_node_count=len(matches))
```

Extend `src/autoagent/executors/complete_detector.py`:

```python
async def wait_for_ui_tree_stable(
    device: Any,
    *,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float = 0.2,
) -> str:
    deadline = time.monotonic() + max_wait_sec
    last_xml: str | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
        now = time.monotonic()
        if xml == last_xml:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_sec:
                return xml
        else:
            last_xml = xml
            stable_since = None
        await asyncio.sleep(poll_interval_sec)
    raise TimeoutError(f"ui_tree_stable not reached within {max_wait_sec}s")
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_response_extractor_ui_tree.py tests/unit/test_complete_detector_android.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/executors/response_extractor.py src/autoagent/executors/complete_detector.py tests/unit/test_response_extractor_ui_tree.py tests/unit/test_complete_detector_android.py
git commit -m "feat(android): add tier1 response extraction and completion detection"
```

---

### Task 11: Implement `AndroidExecutor` and executor factory dispatch

**Files:**
- Create: `src/autoagent/executors/android_executor.py`
- Modify: `src/autoagent/api/_deps.py`
- Modify: `tests/unit/test_executor_factory.py`
- Create: `tests/unit/test_android_executor_unit.py`

- [x] **Step 1: Write the failing executor tests**

Add to `tests/unit/test_executor_factory.py`:

```python
from autoagent.executors.android_executor import AndroidExecutor


def test_gui_android_returns_android_executor() -> None:
    assert isinstance(_build_executor("gui_android"), AndroidExecutor)
```

Create `tests/unit/test_android_executor_unit.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.base import ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    AndroidProfile,
    AndroidReadyCheckTree,
    AndroidResponseExtraction,
    Locator,
    UiTreeStable,
)


@pytest.mark.asyncio
async def test_execute_happy_path(monkeypatch, tmp_path):
    device = MagicMock()
    device.dump_hierarchy.return_value = '<hierarchy><node class="android.widget.TextView" text="echo: hi"/></hierarchy>'
    monkeypatch.setattr("autoagent.executors.android_executor.u2.connect", lambda serial: device)

    profile = AndroidProfile(
        name="fake_android",
        platform="android",
        package="demo.app",
        ready_check=AndroidReadyCheckTree(type="ui_tree_contains", text="echo", timeout_sec=1),
        recovery_path=[],
        input_locator=Locator(type="resource_id", value="demo:id/input"),
        send_button_locator=Locator(type="text", value="Send"),
        response_extraction=AndroidResponseExtraction(
            method="ui_tree_only",
            response_container_locator=Locator(type="resource_id", value="demo:id/list"),
            scroll_container_locator=Locator(type="resource_id", value="demo:id/list"),
            latest_bubble_match=Locator(type="last_child_with_class", value="android.widget.TextView"),
        ),
        complete_detection=UiTreeStable(type="ui_tree_stable", stable_sec=0.0, max_wait_sec=1),
    )
    sample = Sample(id="s1", prompts=["hi"], mode="gui_android", target_profile="fake_android", retry=0)

    out = await AndroidExecutor(screenshots_root=tmp_path).execute(
        sample,
        profile,
        ExecutorContext(device_serial="emulator-5554", verbose_logs=True),
    )

    assert out == ["echo: hi"]
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_executor_factory.py tests/unit/test_android_executor_unit.py -v
```
Expected: FAIL because `AndroidExecutor` is missing and `_build_executor("gui_android")` still raises.

- [x] **Step 3: Implement `AndroidExecutor` and wire factory dispatch**

Create `src/autoagent/executors/android_executor.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import uiautomator2 as u2

from autoagent.config.settings import get_settings
from autoagent.executors.android_action_runner import AndroidActionRunner
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.complete_detector import wait_for_ui_tree_stable
from autoagent.executors.response_extractor import UiTreeExtractor
from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore
from autoagent.models.api import Sample


class AndroidExecutor(Executor):
    def __init__(self, screenshots_root: Path | None = None) -> None:
        self._screenshots_root = screenshots_root or get_settings().logs_root

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not ctx.device_serial:
            raise ValueError("AndroidExecutor requires ctx.device_serial")
        device = await asyncio.to_thread(u2.connect, ctx.device_serial)
        store = ScreenshotStore(self._screenshots_root, ctx.logs_dir or "sync", sample.id)
        extractor = UiTreeExtractor()
        responses: list[str] = []

        await asyncio.to_thread(device.app_start, profile.package, profile.activity, True)
        for idx, prompt in enumerate(sample.prompts, start=1):
            xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
            result = extractor.extract_from_xml(xml, bubble_class=profile.response_extraction.latest_bubble_match.value)
            responses.append(result.text)
            shot = ScreenshotResult(path=store.next_path(f"done_{idx}"), label=f"done_{idx}")
            ctx.screenshot_index.append(shot)
        return responses
```

In `src/autoagent/api/_deps.py`:

```python
from autoagent.executors.android_executor import AndroidExecutor

def _build_executor(mode: str) -> Executor:
    if mode == "api":
        return ApiExecutor()
    if mode == "gui_pc_web":
        return WebExecutor()
    if mode == "gui_android":
        return AndroidExecutor()
    raise ValueError(f"mode {mode} not supported")
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_executor_factory.py tests/unit/test_android_executor_unit.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/executors/android_executor.py src/autoagent/api/_deps.py tests/unit/test_executor_factory.py tests/unit/test_android_executor_unit.py
git commit -m "feat(android): add android executor and factory dispatch"
```

---

### Task 12: Integrate scheduler, events, `/tests/sync`, and batch replay endpoints

**Files:**
- Modify: `src/autoagent/scheduler/batch_scheduler.py`
- Modify: `src/autoagent/api/tests.py`
- Modify: `src/autoagent/api/batches.py`
- Modify: `src/autoagent/storage/samples.py`
- Create: `tests/unit/test_scheduler_device_pool.py`
- Create: `tests/integration/test_tests_sync_android.py`

- [x] **Step 1: Write the failing scheduler/API tests**

`tests/unit/test_scheduler_device_pool.py`:

```python
from autoagent.scheduler.batch_scheduler import _resolve_concurrency


def test_android_concurrency_uses_available_devices() -> None:
    profile = type("P", (), {"platform": "android"})()
    samples = [type("S", (), {"target_profile": "fake_android"})()]
    assert _resolve_concurrency(4, "gui_android", samples, lambda _name: profile, available_devices=2) == 2
```

`tests/integration/test_tests_sync_android.py`:

```python
async def test_sync_android_uses_longer_timeout(client, monkeypatch):
    from autoagent.api import tests as mod

    captured = {}

    class Scheduler:
        async def submit(self, **kwargs):
            captured.update(kwargs)
            return "b1"

        async def wait_done(self, batch_id, timeout_sec):
            captured["timeout_sec"] = timeout_sec

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    async def fake_list(_batch_id):
        return []

    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    h = await _h(client)
    r = await client.post(
        "/api/v1/tests/sync",
        json={"id": "s1", "prompts": ["hi"], "mode": "gui_android", "target_profile": "fake_android"},
        headers=h,
    )
    assert captured["timeout_sec"] == 210
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_scheduler_device_pool.py tests/integration/test_tests_sync_android.py -v
```
Expected: FAIL because `_resolve_concurrency` does not know about Android and `/tests/sync` still uses the generic timeout path.

- [x] **Step 3: Implement device-aware scheduler and replay endpoint**

In `src/autoagent/scheduler/batch_scheduler.py`, extend `_resolve_concurrency` and `run_one()`:

```python
def _resolve_concurrency(..., available_devices: int | None = None) -> int:
    if mode == "gui_android":
        avail = max(1, available_devices or 1)
        return max(1, min(requested, avail))
    # existing web rule follows
```

Inside `run_one()`:

```python
await bus.publish(batch_id, "sample_update", {"sample_id": sample.id, "status": "running"})
ctx = ExecutorContext(verbose_logs=settings.default_verbose_logs)
if sample.mode == "gui_android":
    await bus.publish(
        batch_id,
        "sample_update",
        {"sample_id": sample.id, "status": "running", "waiting_for_device": True},
    )
    async with self._device_pool.acquire(getattr(profile, "serial", None), timeout_sec=60) as serial:
        ctx.device_serial = serial
        await bus.publish(
            batch_id,
            "sample_update",
            {
                "sample_id": sample.id,
                "status": "running",
                "waiting_for_device": False,
                "device_serial": serial,
            },
        )
        result = await executor.run(...)
else:
    result = await executor.run(...)
```

In `src/autoagent/api/tests.py`, keep the same route but set the effective wait window to `180 + 30` for `gui_android`.

In `src/autoagent/api/batches.py`, add:

```python
@router.get("/{batch_id}/samples/{sample_id}/actions.jsonl")
async def download_actions(batch_id: str, sample_id: str) -> FileResponse:
    root = get_settings().logs_root.resolve()
    target = (root / batch_id / sample_id / "actions.jsonl").resolve()
    if not target.is_file():
        raise HTTPException(status_code=404, detail="actions replay not found")
    return FileResponse(target, media_type="application/x-ndjson", filename=f"{sample_id}.actions.jsonl")
```

Also update `list_screenshots()` to prefer `SampleResult.metadata["screenshots"]` so `is_sensitive` survives.

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_scheduler_device_pool.py tests/integration/test_tests_sync_android.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/autoagent/scheduler/batch_scheduler.py src/autoagent/api/tests.py src/autoagent/api/batches.py src/autoagent/storage/samples.py tests/unit/test_scheduler_device_pool.py tests/integration/test_tests_sync_android.py
git commit -m "feat(android): wire scheduler and batch api for devices"
```

---

### Task 13: Add the fake-chat APK fixture and real-device Tier 1 tests

> Execution note (2026-04-23): the user chose to skip local `fake_chat-debug.apk` build/installation in this coding session. Keep the fixture source and `@pytest.mark.android` test in the repo, but treat APK-backed execution as deferred to final manual validation on a real device and real target app.

**Files:**
- Create: `tests/fixtures/fake_chat_apk/README.md`
- Create: `tests/fixtures/fake_chat_apk/app/src/main/AndroidManifest.xml`
- Create: `tests/fixtures/fake_chat_apk/app/src/main/java/com/autoagent/fakechat/MainActivity.kt`
- Create: `tests/fixtures/fake_chat_apk/app/src/main/res/layout/activity_main.xml`
- Create: `tests/integration/test_android_executor_e2e.py`

- [x] **Step 1: Write the failing `@pytest.mark.android` test**

`tests/integration/test_android_executor_e2e.py`:

```python
import os

import pytest

from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.base import ExecutorContext
from autoagent.models.api import Sample

pytestmark = pytest.mark.android


@pytest.mark.asyncio
async def test_fake_chat_apk_round_trip(android_profile, android_serial, tmp_path):
    sample = Sample(
        id="s1",
        prompts=["hi", "bb", "ccc"],
        mode="gui_android",
        target_profile="fake_android",
        retry=0,
    )
    result = await AndroidExecutor(screenshots_root=tmp_path).run(
        sample,
        profile=android_profile,
        default_timeout_sec=180,
        ctx=ExecutorContext(device_serial=android_serial, verbose_logs=True),
    )
    assert result.status == "done"
    assert result.responses == ["echo: hi", "echo: bb", "echo: ccc"]
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/integration/test_android_executor_e2e.py -m android -v
```
Expected: FAIL/skip until a built APK artifact is supplied. In this session the test is allowed to skip when `AUTOAGENT_FAKE_CHAT_APK` is absent.

- [x] **Step 3: Add the fixture app and install flow**

Use a minimal one-screen Android app. `MainActivity.kt`:

```kotlin
class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val input = findViewById<EditText>(R.id.input)
        val send = findViewById<Button>(R.id.send)
        val list = findViewById<LinearLayout>(R.id.responses)
        val reset = findViewById<Button>(R.id.newChat)

        send.setOnClickListener {
            val view = TextView(this)
            view.text = "echo: ${input.text}"
            list.addView(view)
            input.setText("")
        }
        reset.setOnClickListener { list.removeAllViews() }
    }
}
```

`activity_main.xml` should define resource IDs `@+id/input`, `@+id/send`, `@+id/newChat`, and `@+id/responses` so the Android profile can target them.

In `tests/integration/test_android_executor_e2e.py`, add session fixtures that run:

```python
subprocess.run(["adb", "-s", android_serial, "install", "-r", str(apk_path)], check=True)
```

and construct a matching `AndroidProfile` using `ui_tree_only`.

- [ ] **Step 4: Run the real-device test**

Run:
```bash
python3.11 -m pytest tests/integration/test_android_executor_e2e.py -m android -v
```
Expected: PASS on a machine with a connected device/emulator and a built APK. Deferred from this session by user request; final validation will happen against a real device + real app.

- [x] **Step 5: Commit**

```bash
git add tests/fixtures/fake_chat_apk tests/integration/test_android_executor_e2e.py
git commit -m "test(android): add fake chat apk fixture and tier1 e2e"
```

---

### Task 14: Add frontend device API types and hooks

**Files:**
- Modify: `web/src/types/api.ts`
- Create: `web/src/api/devices.ts`
- Create: `web/src/api/devices.test.ts`

- [x] **Step 1: Write the failing frontend type/hook test**

Create `web/src/api/devices.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'

import { client } from './client'
import { useDevices } from './devices'

describe('devices api', () => {
  it('exports the devices hook', () => {
    expect(typeof useDevices).toBe('function')
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
pnpm --dir web test -- src/api/devices.test.ts
```
Expected: FAIL with `Cannot find module './devices'`.

- [x] **Step 3: Add the shared frontend types and hooks**

In `web/src/types/api.ts`, add:

```ts
export interface Device {
  serial: string
  label: string | null
  model: string | null
  android_version: string | null
  online: boolean
  enabled: boolean
  last_seen_at: string | null
}

export interface SampleUpdate {
  sample_id: string
  status: SampleStatus
  device_serial?: string | null
  waiting_for_device?: boolean
}
```

Create `web/src/api/devices.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { client } from './client'
import { Device } from '../types/api'

export function useDevices() {
  return useQuery({
    queryKey: ['devices'],
    queryFn: async () => (await client.get<Device[]>('/devices')).data,
    refetchInterval: 10_000,
  })
}

export function useRefreshDevices() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await client.post<Device[]>('/devices/refresh')).data,
    onSuccess: (rows) => queryClient.setQueryData(['devices'], rows),
  })
}
```

- [x] **Step 4: Run the focused test**

Run:
```bash
pnpm --dir web test -- src/api/devices.test.ts
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/types/api.ts web/src/api/devices.ts web/src/api/devices.test.ts
git commit -m "feat(web): add device api types and hooks"
```

---

### Task 15: Build the `/devices` page and route it into the app shell

**Files:**
- Create: `web/src/pages/Devices/Index.tsx`
- Modify: `web/src/pages/Devices/Index.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/components/AppLayout.tsx`

- [x] **Step 1: Write the failing page test**

`web/src/pages/Devices/Index.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DevicesPage } from './Index'

vi.mock('../../api/devices', () => ({
  useDevices: () => ({
    data: [{ serial: 'emulator-5554', label: 'Pixel 8', model: 'sdk', android_version: '14', online: true, enabled: true }],
    isLoading: false,
  }),
  useRefreshDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

it('renders device rows', () => {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DevicesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
  expect(screen.getByText('emulator-5554')).toBeInTheDocument()
  expect(screen.getByText('Pixel 8')).toBeInTheDocument()
})
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
pnpm --dir web test -- src/pages/Devices/Index.test.tsx
```
Expected: FAIL with `Cannot find module './Index'`.

- [x] **Step 3: Implement the page and route**

Create `web/src/pages/Devices/Index.tsx`:

```tsx
import { Button, Card, Empty, Space, Table, Tag, Typography } from 'antd'
import { useDevices, useRefreshDevices } from '../../api/devices'

export function DevicesPage() {
  const devices = useDevices()
  const refresh = useRefreshDevices()

  if (!devices.data?.length && !devices.isLoading) {
    return (
      <Card>
        <Empty description="暂无设备" />
      </Card>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Devices
        </Typography.Title>
        <Button onClick={() => refresh.mutateAsync()} loading={refresh.isPending}>
          立即刷新
        </Button>
      </Space>
      <Table
        rowKey="serial"
        dataSource={devices.data ?? []}
        pagination={false}
        columns={[
          { title: 'Serial', dataIndex: 'serial' },
          { title: 'Label', dataIndex: 'label', render: (value) => value ?? '-' },
          { title: 'Model', dataIndex: 'model', render: (value) => value ?? '-' },
          { title: 'Android', dataIndex: 'android_version', render: (value) => value ?? '-' },
          {
            title: '状态',
            render: (_, row) => (
              <Space>
                <Tag color={row.online ? 'green' : 'default'}>{row.online ? 'online' : 'offline'}</Tag>
                <Tag color={row.enabled ? 'blue' : 'default'}>{row.enabled ? 'enabled' : 'disabled'}</Tag>
              </Space>
            ),
          },
        ]}
      />
    </Space>
  )
}
```

In `web/src/App.tsx`, add:

```tsx
import { DevicesPage } from './pages/Devices/Index'
// ...
<Route path="devices" element={<DevicesPage />} />
```

In `web/src/components/AppLayout.tsx`, add a `Devices` menu item.

- [x] **Step 4: Run the focused test**

Run:
```bash
pnpm --dir web test -- src/pages/Devices/Index.test.tsx
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add web/src/pages/Devices/Index.tsx web/src/pages/Devices/Index.test.tsx web/src/App.tsx web/src/components/AppLayout.tsx
git commit -m "feat(web): add devices management page"
```

---

### Task 16: Add Android mode/profile selection and connectivity support in the frontend

**Files:**
- Modify: `web/src/pages/Batches/New.tsx`
- Create: `web/src/pages/Batches/New.test.tsx`
- Modify: `web/src/pages/Tests/Quick.tsx`
- Create: `web/src/pages/Tests/Quick.test.tsx`
- Modify: `web/src/pages/Profiles/Edit.tsx`
- Modify: `web/src/pages/Profiles/ConnectivityTestModal.tsx`
- Modify: `web/src/pages/Profiles/Edit.test.tsx`

- [x] **Step 1: Write the failing UI tests**

Extend `web/src/pages/Profiles/Edit.test.tsx`:

```tsx
it('enables connectivity test for android profiles', async () => {
  render(<ProfileEdit />, { wrapper: makeWrapper('/profiles/fake_android') })
  await userEvent.type(screen.getByRole('textbox'), 'name: fake_android\nplatform: android\npackage: demo')
  expect(screen.getByRole('button', { name: '连通性测试' })).toBeEnabled()
})
```

Create `web/src/pages/Batches/New.test.tsx` and `web/src/pages/Tests/Quick.test.tsx` with assertions that the mode select includes `Android (GUI)` and filters profiles to `platform === 'android'`.

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
pnpm --dir web test -- src/pages/Profiles/Edit.test.tsx src/pages/Batches/New.test.tsx src/pages/Tests/Quick.test.tsx
```
Expected: FAIL because only API/Web are wired today.

- [x] **Step 3: Implement the UI changes**

In `web/src/pages/Profiles/Edit.tsx`, extend the `profileMode` detection:

```tsx
const profileMode = useMemo(() => {
  if (/^platform:\s*android\b/m.test(yaml)) return 'gui_android' as const
  if (/^platform:\s*web\b/m.test(yaml)) return 'gui_pc_web' as const
  if (/^platform:\s*api\b/m.test(yaml)) return 'api' as const
  return null
}, [yaml])
```

In `web/src/pages/Profiles/ConnectivityTestModal.tsx`, treat Android like other GUI modes:

```tsx
timeout_sec: mode === 'api' ? 60 : 180
```

In `web/src/pages/Batches/New.tsx` and `web/src/pages/Tests/Quick.tsx`, add:

```tsx
{ label: 'Android (GUI)', value: 'gui_android' }
```

and update the platform mapping:

```tsx
const selectedPlatform =
  mode === 'gui_pc_web' ? 'web' : mode === 'gui_android' ? 'android' : 'api'
```

Also add the helper text under concurrency in `BatchNew.tsx`:

```tsx
<Typography.Text type="secondary">
  Android 模式下，实际并发上限取决于在线可用设备数。
</Typography.Text>
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
pnpm --dir web test -- src/pages/Profiles/Edit.test.tsx src/pages/Batches/New.test.tsx src/pages/Tests/Quick.test.tsx
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add web/src/pages/Batches/New.tsx web/src/pages/Batches/New.test.tsx web/src/pages/Tests/Quick.tsx web/src/pages/Tests/Quick.test.tsx web/src/pages/Profiles/Edit.tsx web/src/pages/Profiles/ConnectivityTestModal.tsx web/src/pages/Profiles/Edit.test.tsx
git commit -m "feat(web): add android mode and connectivity support"
```

---

### Task 17: Surface Android metadata in batch/sample detail and apply `sample_update` SSE events

**Files:**
- Modify: `web/src/hooks/useBatchStream.ts`
- Modify: `web/src/pages/Batches/SampleDetail.tsx`
- Modify: `web/src/pages/Batches/SampleDetail.test.tsx`
- Modify: `web/src/components/ScreenshotStrip.tsx`
- Modify: `web/src/api/batches.ts`

- [x] **Step 1: Write the failing tests**

Extend `web/src/hooks/useBatchStream.test.ts`:

```tsx
it('applies sample_update device fields', () => {
  const prev = {
    batch_id: 'b1',
    status: 'running',
    mode: 'gui_android',
    total: 1,
    done: 0,
    failed: 0,
    concurrency: 1,
    samples: [{ id: 's1', status: 'running' }],
    seq: 1,
  }
  const next = applyEvent(prev, {
    seq: 2,
    kind: 'sample_update',
    payload: { sample_id: 's1', status: 'running', device_serial: 'emulator-5554', waiting_for_device: false },
    ts: '2026-04-22T00:00:00Z',
  })
  expect(next.samples[0].device_serial).toBe('emulator-5554')
})
```

Extend `web/src/pages/Batches/SampleDetail.test.tsx`:

```tsx
expect(screen.getByText(/运行设备/i)).toBeInTheDocument()
expect(screen.getByRole('button', { name: /下载回放/i })).toBeInTheDocument()
```

- [x] **Step 2: Run the tests to verify they fail**

Run:
```bash
pnpm --dir web test -- src/hooks/useBatchStream.test.ts src/pages/Batches/SampleDetail.test.tsx
```
Expected: FAIL because `applyEvent()` ignores `sample_update` and `SampleDetail` does not show Android metadata.

- [x] **Step 3: Implement sample-update merging and sample detail UI**

In `web/src/hooks/useBatchStream.ts`, add `sample_update` handling:

```tsx
if (event.kind === 'sample_update') {
  const payload = event.payload as SampleUpdate
  next.samples = next.samples.map((sample) =>
    sample.id === payload.sample_id
      ? {
          ...sample,
          status: payload.status ?? sample.status,
          device_serial: payload.device_serial ?? sample.device_serial,
          waiting_for_device: payload.waiting_for_device ?? sample.waiting_for_device,
        }
      : sample,
  )
}
```

In `web/src/pages/Batches/SampleDetail.tsx`, add Android-only fields:

```tsx
<Descriptions.Item label="运行设备">
  {(sample.device_serial as string | undefined) ??
    (sample.metadata?.device_serial as string | undefined) ??
    '-'}
</Descriptions.Item>
```

Add a replay download button:

```tsx
{sample.metadata?.action_replay_available ? (
  <Button onClick={() => downloadSampleActions(data.batch_id, sample.id)}>下载回放 JSONL</Button>
) : null}
```

In `web/src/components/ScreenshotStrip.tsx`, render a locked placeholder when `shot.is_sensitive` is true.

- [x] **Step 4: Run the focused tests**

Run:
```bash
pnpm --dir web test -- src/hooks/useBatchStream.test.ts src/pages/Batches/SampleDetail.test.tsx
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/hooks/useBatchStream.ts web/src/pages/Batches/SampleDetail.tsx web/src/pages/Batches/SampleDetail.test.tsx web/src/components/ScreenshotStrip.tsx web/src/api/batches.ts
git commit -m "feat(web): show android sample metadata and replay download"
```

---

### Task 18: Tier 1 verification, docs, and release tag

> Execution note (2026-04-23): final Tier 1 manual validation is now defined as user-run testing on a real device and real app. The fake-chat fixture remains optional scaffolding, not a gating requirement for this session.

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-04-22-plan-4-android-executor-design.md`

- [ ] **Step 1: Record Tier 1 verification commands in docs**

Add to `CLAUDE.md`:

```md
- Tier 1 Android smoke:
  1. `adb devices -l`
  2. `/devices` shows the device and it can be enabled
  3. save a `platform: android` profile for a real target app
  4. run `Tests / Quick` with `mode=gui_android`
  5. run a 3-sample Android batch and verify SSE/sample detail screenshots
  6. optionally run the `fake_chat_apk` fixture if a built APK is available
```

Update `README.md` project status to:

```md
**Plan 1 complete. Plan 2 complete. Plan 3 complete. Plan 4 Tier 1 complete.**
```

- [ ] **Step 2: Run the full Tier 1 verification matrix**

Run:
```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
python3.11 -m pytest -v -m android
python3.11 -m ruff check .
python3.11 -m ruff format --check .
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web format:check
pnpm --dir web build
```
Expected: all non-Android checks pass. Android real-device checks are optional in-session and may be skipped until the user performs final validation on a prepared machine.

- [ ] **Step 3: Execute the manual Tier 1 smoke**

Use the browser UI to verify on a real device and real target app:

```text
1. /devices can refresh and show the connected device
2. enable the device if needed
3. create an android profile for the real target app
4. run Tests / Quick with prompt "hi"
5. create a 3-sample gui_android batch
6. watch BatchDetail update via SSE
7. open SampleDetail and verify screenshots + action log + device serial
8. download actions.jsonl successfully
```

- [ ] **Step 4: Commit the Tier 1 completion docs**

```bash
git add README.md CLAUDE.md docs/superpowers/specs/2026-04-22-plan-4-android-executor-design.md
git commit -m "docs(android): record tier1 completion and verification"
```

- [ ] **Step 5: Tag Tier 1**

```bash
git tag -a android-executor-tier1-v0.4.0 -m "Plan 4 Tier 1 complete: Android Executor"
```

---

## Tier 2 — OCR, long responses, and `pixel_stable`

### Task 19: Add OCR dependencies and Tier 2 operator notes

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [x] **Step 1: Write the failing import check**

Run:
```bash
python3.11 - <<'PY'
import importlib
importlib.import_module("rapidocr_onnxruntime")
print("ok")
PY
```
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 2: Add the OCR dependency**

In `pyproject.toml`, append:

```toml
"rapidocr_onnxruntime>=1.4,<2.0",
```

- [x] **Step 3: Document Tier 2 runtime expectations**

Add to `README.md` and `CLAUDE.md`:

```md
- Tier 2 OCR uses `rapidocr_onnxruntime` on CPU.
- Long responses may take several seconds because multiple frames are OCR'd and stitched.
- `@pytest.mark.slow` covers OCR fixtures and is excluded from the fast suite.
```

- [x] **Step 4: Install deps and verify fast suites stay green**

Run:
```bash
python3.11 -m pip install -e '.[dev]'
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md CLAUDE.md
git commit -m "chore(android): add rapidocr dependency"
```

---

### Task 20: Implement the OCR engine and OCR/hybrid extractors

**Files:**
- Create: `src/autoagent/executors/ocr.py`
- Modify: `src/autoagent/executors/response_extractor.py`
- Create: `tests/unit/test_response_extractor_ocr.py`

- [x] **Step 1: Write the failing OCR tests**

`tests/unit/test_response_extractor_ocr.py`:

```python
from autoagent.executors.response_extractor import HybridExtractor, _is_suspect


def test_is_suspect_detects_short_or_truncated_text() -> None:
    assert _is_suspect("")
    assert _is_suspect("..")
    assert _is_suspect("abc…")
    assert not _is_suspect("完整回答")
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_response_extractor_ocr.py -v
```
Expected: FAIL because `_is_suspect` and OCR classes do not exist.

- [x] **Step 3: Implement the OCR engine and extractors**

Create `src/autoagent/executors/ocr.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

_engine_instance = None
_engine_error: Exception | None = None


@dataclass
class OcrLine:
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float


async def get_engine():
    global _engine_instance, _engine_error
    if _engine_error is not None:
        raise RuntimeError("OCR init failed previously") from _engine_error
    if _engine_instance is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine_instance = RapidOCR()
        except Exception as e:
            _engine_error = e
            raise
    return _engine_instance
```

Extend `src/autoagent/executors/response_extractor.py`:

```python
def _is_suspect(text: str) -> bool:
    stripped = text.strip()
    return not stripped or len(stripped) < 3 or stripped.endswith(("...", "…")) or "\ufffc" in stripped


class OcrExtractor:
    async def extract(self, frames: list[bytes]) -> ExtractionResult:
        engine = await get_engine()
        # actual recognition body arrives in Task 21
        return ExtractionResult(text="", method_used="ocr", frames=len(frames))


class HybridExtractor:
    def __init__(self, ui_tree: UiTreeExtractor, ocr: OcrExtractor) -> None:
        self.ui_tree = ui_tree
        self.ocr = ocr
```

- [x] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_response_extractor_ocr.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/executors/ocr.py src/autoagent/executors/response_extractor.py tests/unit/test_response_extractor_ocr.py
git commit -m "feat(android): add ocr engine and hybrid extractor scaffolding"
```

---

### Task 21: Add `ScrollStitcher` and line de-duplication

**Files:**
- Create: `src/autoagent/executors/scroll_stitcher.py`
- Create: `tests/unit/test_scroll_stitcher.py`
- Modify: `src/autoagent/executors/response_extractor.py`

- [x] **Step 1: Write the failing stitcher tests**

`tests/unit/test_scroll_stitcher.py`:

```python
from autoagent.executors.scroll_stitcher import stitch_lines


def test_stitch_lines_dedupes_overlap() -> None:
    frames = [
        ["第一行", "第二行", "第三行"],
        ["第三行", "第四行", "第五行"],
    ]
    assert stitch_lines(frames) == "第一行\n第二行\n第三行\n第四行\n第五行"
```

- [x] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_scroll_stitcher.py -v
```
Expected: FAIL because the stitcher module does not exist.

- [x] **Step 3: Implement the stitcher**

Create `src/autoagent/executors/scroll_stitcher.py`:

```python
from __future__ import annotations


def stitch_lines(frames: list[list[str]]) -> str:
    merged: list[str] = []
    for frame in frames:
        normalized = [line.strip() for line in frame if line.strip()]
        overlap = 0
        for n in range(min(3, len(merged), len(normalized)), 0, -1):
            if merged[-n:] == normalized[:n]:
                overlap = n
                break
        merged.extend(normalized[overlap:])
    return "\n".join(merged)
```

Update `OcrExtractor.extract()` in `response_extractor.py` to use `stitch_lines()` on OCR frame outputs.

- [x] **Step 4: Run the focused test**

Run:
```bash
python3.11 -m pytest tests/unit/test_scroll_stitcher.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/executors/scroll_stitcher.py src/autoagent/executors/response_extractor.py tests/unit/test_scroll_stitcher.py
git commit -m "feat(android): add scroll stitcher for long responses"
```

---

### Task 22: Add `pixel_stable` and final Tier 2 executor wiring

**Files:**
- Modify: `src/autoagent/executors/complete_detector.py`
- Modify: `src/autoagent/executors/android_executor.py`
- Modify: `tests/unit/test_complete_detector_android.py`
- Modify: `tests/unit/test_android_executor_unit.py`

- [ ] **Step 1: Write the failing `pixel_stable` tests**

Extend `tests/unit/test_complete_detector_android.py`:

```python
import pytest

from autoagent.executors.complete_detector import wait_for_pixel_stable


@pytest.mark.asyncio
async def test_wait_for_pixel_stable_hashes_same_frames(monkeypatch):
    seq = iter([b"a", b"a", b"a"])

    class Device:
        def screenshot(self, format="raw"):
            return next(seq)

    await wait_for_pixel_stable(Device(), stable_sec=0.0, max_wait_sec=0.2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
python3.11 -m pytest tests/unit/test_complete_detector_android.py tests/unit/test_android_executor_unit.py -v
```
Expected: FAIL because `wait_for_pixel_stable` does not exist and the executor does not select Tier 2 strategies.

- [ ] **Step 3: Implement `pixel_stable` and strategy dispatch**

In `src/autoagent/executors/complete_detector.py`, add:

```python
import hashlib


async def wait_for_pixel_stable(
    device: Any,
    *,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float = 0.5,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    last_hash: str | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        raw = await asyncio.to_thread(device.screenshot, format="raw")
        digest = hashlib.md5(raw).hexdigest()
        now = time.monotonic()
        if digest == last_hash:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_sec:
                return
        else:
            last_hash = digest
            stable_since = None
        await asyncio.sleep(poll_interval_sec)
    raise TimeoutError(f"pixel_stable not reached within {max_wait_sec}s")
```

In `src/autoagent/executors/android_executor.py`, dispatch by `profile.response_extraction.method` and `profile.complete_detection.type`, raising `NotImplementedError` for OCR modes before Tier 2 and using the new OCR/pixel helpers afterwards.

- [ ] **Step 4: Run the focused tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_complete_detector_android.py tests/unit/test_android_executor_unit.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/executors/complete_detector.py src/autoagent/executors/android_executor.py tests/unit/test_complete_detector_android.py tests/unit/test_android_executor_unit.py
git commit -m "feat(android): add pixel stable and tier2 executor wiring"
```

---

### Task 23: Add Tier 2 screenshot fixtures and slow OCR coverage

**Files:**
- Create: `tests/fixtures/android_screenshots/README.md`
- Create: `tests/fixtures/android_screenshots/*.png`
- Create: `tests/fixtures/android_screenshots/*.expected.txt`
- Modify: `tests/unit/test_response_extractor_ocr.py`
- Modify: `tests/integration/test_android_executor_e2e.py`

- [ ] **Step 1: Write the failing OCR fixture test**

Extend `tests/unit/test_response_extractor_ocr.py`:

```python
from pathlib import Path

import pytest

from autoagent.executors.response_extractor import OcrExtractor

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_ocr_fixture_matches_expected() -> None:
    fixture_dir = Path("tests/fixtures/android_screenshots")
    image = fixture_dir / "long_reply_01.png"
    expected = (fixture_dir / "long_reply_01.expected.txt").read_text(encoding="utf-8").strip()
    result = await OcrExtractor().extract_from_paths([image])
    assert result.text.strip() == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_response_extractor_ocr.py -m slow -v
```
Expected: FAIL because fixture files and `extract_from_paths()` do not exist yet.

- [ ] **Step 3: Add OCR fixtures and slow-path tests**

Create the screenshot fixture directory with a README that records:

```md
- source device / emulator
- app under test
- whether the image represents one screen or a multi-screen response
- expected stitched text file path
```

Extend `OcrExtractor` with:

```python
async def extract_from_paths(self, paths: list[Path]) -> ExtractionResult:
    frames = [path.read_bytes() for path in paths]
    return await self.extract(frames)
```

Add one `@pytest.mark.android` Tier 2 e2e case in `tests/integration/test_android_executor_e2e.py` that uses `ocr_only` or `ui_tree_then_ocr` against a long-response fixture app/profile.

- [ ] **Step 4: Run the slow and android verification**

Run:
```bash
python3.11 -m pytest tests/unit/test_response_extractor_ocr.py -m slow -v
python3.11 -m pytest tests/integration/test_android_executor_e2e.py -m android -v
```
Expected: PASS on a prepared machine.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/android_screenshots tests/unit/test_response_extractor_ocr.py tests/integration/test_android_executor_e2e.py
git commit -m "test(android): add tier2 ocr fixtures and coverage"
```

---

### Task 24: Tier 2 verification, docs, and final tag

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-04-22-plan-4-android-executor-design.md`

- [ ] **Step 1: Update docs to mark Plan 4 complete**

Set the repo status lines to:

```md
**Plan 1 complete. Plan 2 complete. Plan 3 complete. Plan 4 complete.**
```

In `CLAUDE.md`, add the Tier 2 smoke checklist:

```md
- Tier 2 Android smoke:
  1. run a long-response app/profile with `method: ocr_only` or `ui_tree_then_ocr`
  2. verify stitched text spans more than one screen
  3. verify `pixel_stable` or `ui_tree_stable` completes without false positives
```

- [ ] **Step 2: Run the full Plan 4 verification matrix**

Run:
```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
python3.11 -m pytest -v -m android
python3.11 -m pytest -v -m slow
python3.11 -m ruff check .
python3.11 -m ruff format --check .
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web format:check
pnpm --dir web build
```
Expected: all pass.

- [ ] **Step 3: Run the final manual smoke**

Verify end to end:

```text
1. /devices shows at least one online+enabled device
2. Tier 1 fake-chat profile still runs
3. Tier 2 OCR profile extracts a >1 screen response
4. BatchDetail updates live without reload
5. SampleDetail shows screenshots, action log, device serial, and replay download
6. disabling one device mid-run only fails the in-flight sample on that device
```

- [ ] **Step 4: Commit the completion docs**

```bash
git add README.md CLAUDE.md docs/superpowers/specs/2026-04-22-plan-4-android-executor-design.md
git commit -m "docs(android): mark Plan 4 complete"
```

- [ ] **Step 5: Tag the final release**

```bash
git tag -a android-executor-v0.4.0 -m "Plan 4 complete: Android Executor + OCR"
```

---

## Self-Review

- **Spec coverage:** Tier 1 device discovery, scheduler/device pool, Android executor flow, `/devices` endpoints, SSE/sample metadata, screenshots/action replay, frontend device UI, and manual smoke are covered by Tasks 1-18. Tier 2 OCR engine, hybrid extraction, scroll stitching, `pixel_stable`, fixture coverage, and final release are covered by Tasks 19-24.
- **Deliberate design choice:** Connectivity testing continues to reuse the existing `Tests / Quick` / `/tests/sync` flow instead of introducing a separate `/profiles/{name}/test` endpoint. This keeps Plan 4 aligned with the current Plan 3 frontend and avoids duplicating execution logic.
- **Placeholder scan:** No `TODO`/`TBD` placeholders should remain. Each task names exact files, commands, and concrete code entry points.
- **Type consistency:** `gui_android`, `platform: android`, `DeviceInfo`, `ScreenshotResult`, `action_replay_available`, and `device_serial` are the canonical names used throughout this plan.
