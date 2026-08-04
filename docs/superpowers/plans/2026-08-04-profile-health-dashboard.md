# Profile Health Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dedicated dashboard page showing each profile as a health card (worst-of status block + success rate / avg duration / unacked anomalies / device-pool status over the last 7 days), backed by a `GET /api/v1/profiles/health` endpoint.

**Architecture:** New `src/autoagent/health/profile_health.py` (`compute_health` pure function + `list_profile_health` assembly). New per-profile windowed aggregate queries in `storage/samples.py` and `anomalies/store.py`. Endpoint added to the existing profiles router. Frontend adds a data layer, a card-grid page, a route, a nav entry, and a small Anomaly Center URL-prefilter.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (SQLite); React 18 + TS + AntD 5, TanStack Query, Vitest.

---

## Context an implementer needs

- **`Sample`** (`models/db.py`): `.status` (`done|failed|timeout|extraction_failed|queued|running|cancelled`), `.target_profile`, `.duration_ms` (nullable), `.ended_at` (nullable; a terminal sample always has one). No `created_at`.
- **Terminal-executed statuses** (success-rate denominator): `done, failed, timeout, extraction_failed` — same set as `notifications/rules.py::_DEVICE_EXECUTED_STATUSES`.
- **`avg_duration_by_profile()`** (`storage/samples.py:114`): currently all-time, `WHERE duration_ms IS NOT NULL GROUP BY target_profile`, returns `{profile: float}`. This task **extends it** with an optional `since` param (default `None` = unchanged behavior, so existing callers in `api/profiles.py` and `storage/batches.py` are unaffected).
- **`anomalies/store.py`** already has `count_unacknowledged()`; this adds a per-profile windowed variant. `Anomaly` columns: `.target_profile`, `.acknowledged`, `.created_at`.
- **`list_devices()`** (`storage/devices.py:59`) → `list[DeviceInfo]` with `.serial`, `.online` (bool), `.enabled` (bool).
- **Profiles**: `profiles.registry.list_profile_names()` → names; `load_profile(name)` → a profile object with `.name`, `.platform` (`api|gui_pc_web|gui_android|agent_android`... — the string), `.serial` (android, optional), `.serials` (android list, optional). See `api/profiles.py::list_profiles` (lines 54-74) for the exact serial-merge pattern to copy.
- **Profiles router** (`api/profiles.py`): `router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(require_user)])`. Add the new route here.
- **Datetime**: use `datetime.now(timezone.utc)`. Tests seed `ended_at`/`created_at` with `datetime.now(timezone.utc)` and pass a `since` computed the same way, so the SQL comparison is apples-to-apples.
- **Tests**: `pytest-asyncio` auto mode; storage/unit tests call `await init_db()` first (see `tests/unit/test_anomaly_store.py`). Integration tests use the `client`/`_login` fixtures (see `tests/integration/test_anomalies_endpoints.py` — copy them). Run: `uv run pytest -q <path>`. Lint: `uv run ruff check .` (pipe-free so exit code isn't masked: `uv run ruff check <files>; echo "EXIT=$?"`).
- **Frontend**: hooks in `web/src/api/*.ts` over `client`; pages in `web/src/pages/*`; types in `web/src/types/api.ts`; nav in `web/src/components/AppLayout.tsx` (`NAV` array, 资源 group); routes in `web/src/App.tsx`. `ProfileDeviceScreensModal` exists (`web/src/components/ProfileDeviceScreensModal.tsx`) for the device click-through. **pnpm cwd resets** → prefix with `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web &&`.

---

## File Structure

- Modify `src/autoagent/storage/samples.py` (add `success_stats_by_profile`; extend `avg_duration_by_profile` with `since`)
- Modify `src/autoagent/anomalies/store.py` (add `unacked_counts_by_profile`)
- Create `src/autoagent/health/__init__.py`, `src/autoagent/health/profile_health.py` (`compute_health` + `list_profile_health`)
- Modify `src/autoagent/models/api.py` (add `ProfileHealth`)
- Modify `src/autoagent/api/profiles.py` (add `GET /health`)
- Create `web/src/api/profileHealth.ts`; modify `web/src/types/api.ts`
- Create `web/src/pages/Profiles/Health.tsx`; modify `web/src/App.tsx`, `web/src/components/AppLayout.tsx`
- Modify `web/src/pages/System/Anomalies.tsx` (URL `target_profile` prefilter)
- Tests: `tests/unit/test_profile_health_queries.py`, `tests/unit/test_compute_health.py`, `tests/unit/test_list_profile_health.py`, `tests/integration/test_profile_health_endpoint.py`; `web/src/api/profileHealth.test.ts`, `web/src/pages/Profiles/Health.test.tsx`, extend `web/src/pages/System/Anomalies.test.tsx`

---

## Task 1: Windowed storage queries for samples

**Files:** Modify `src/autoagent/storage/samples.py`; Test `tests/unit/test_profile_health_queries.py`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_profile_health_queries.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import avg_duration_by_profile, success_stats_by_profile, upsert_sample


def _sample(sid, profile, status, ms, ended):
    return SampleResult(
        id=sid, status=status, mode="api", target_profile=profile, duration_ms=ms, ended_at=ended
    )


@pytest.mark.asyncio
async def test_success_stats_and_windowed_avg():
    await init_db()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=30)
    # profile p: recent 3 done + 1 failed; plus 1 old done (out of window)
    await upsert_sample("b", _sample("s1", "p", "done", 100, now))
    await upsert_sample("b", _sample("s2", "p", "done", 200, now))
    await upsert_sample("b", _sample("s3", "p", "done", 300, now))
    await upsert_sample("b", _sample("s4", "p", "failed", None, now))
    await upsert_sample("b", _sample("s5", "p", "done", 9999, old))
    # a non-terminal sample must NOT count toward the denominator
    await upsert_sample("b", _sample("s6", "p", "running", None, None))

    since = now - timedelta(days=7)
    stats = await success_stats_by_profile(since)
    assert stats["p"] == (3, 4)  # 3 done out of 4 terminal in-window

    avg = await avg_duration_by_profile(since=since)
    assert round(avg["p"]) == 200  # (100+200+300)/3, old 9999 excluded

    # default (all-time) still includes the old sample
    avg_all = await avg_duration_by_profile()
    assert avg_all["p"] > 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_profile_health_queries.py`
Expected: FAIL — `success_stats_by_profile` undefined.

- [ ] **Step 3: Implement** — in `src/autoagent/storage/samples.py`, add the terminal-status constant near the top (after imports) and the new function, and extend `avg_duration_by_profile`:

```python
_TERMINAL_EXECUTED = ("done", "failed", "timeout", "extraction_failed")


async def success_stats_by_profile(since) -> dict[str, tuple[int, int]]:
    """Per profile: (done_count, terminal_count) among samples that finished
    executing (status in _TERMINAL_EXECUTED) with ended_at >= since. Non-
    terminal statuses (queued/running/cancelled) are excluded from the
    denominator — success rate is done / (things that actually ran)."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow.target_profile, SampleRow.status, func.count())
            .where(SampleRow.status.in_(_TERMINAL_EXECUTED))
            .where(SampleRow.ended_at.is_not(None))
            .where(SampleRow.ended_at >= since)
            .group_by(SampleRow.target_profile, SampleRow.status)
        )
        out: dict[str, tuple[int, int]] = {}
        for profile, status, count in r.all():
            done, total = out.get(profile, (0, 0))
            total += count
            if status == "done":
                done += count
            out[profile] = (done, total)
        return out
```

Then change `avg_duration_by_profile` to accept `since`:

```python
async def avg_duration_by_profile(since=None) -> dict[str, float]:
    """Average Sample.duration_ms grouped by target_profile. When `since` is
    given, only samples with ended_at >= since count (the health dashboard's
    7-day window); default None = all-time (the Profiles list / batch
    duration-anomaly callers, unchanged)."""
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(SampleRow.target_profile, func.avg(SampleRow.duration_ms))
            .where(SampleRow.duration_ms.is_not(None))
            .group_by(SampleRow.target_profile)
        )
        if since is not None:
            stmt = stmt.where(SampleRow.ended_at.is_not(None)).where(SampleRow.ended_at >= since)
        r = await s.execute(stmt)
        return {profile: float(avg) for profile, avg in r.all() if avg is not None}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_profile_health_queries.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/storage/samples.py tests/unit/test_profile_health_queries.py; echo "EXIT=$?"
git add src/autoagent/storage/samples.py tests/unit/test_profile_health_queries.py
git commit -m "feat(health): add per-profile success stats + windowed avg duration"
```

---

## Task 2: Per-profile unacked anomaly counts

**Files:** Modify `src/autoagent/anomalies/store.py`; Test `tests/unit/test_anomaly_store.py` (extend).

- [ ] **Step 1: Write the failing test** — add to `tests/unit/test_anomaly_store.py`:

```python
@pytest.mark.asyncio
async def test_unacked_counts_by_profile():
    from datetime import datetime, timedelta, timezone

    await init_db()
    now = datetime.now(timezone.utc)
    for i in range(3):
        await store.record_anomaly(
            type="duration", batch_id="b", sample_id=f"s{i}", target_profile="p1",
            device_serial=None, summary="x", detail={},
        )
    await store.record_anomaly(
        type="anr", batch_id="b", sample_id="sx", target_profile="p2",
        device_serial=None, summary="y", detail={},
    )
    # acknowledge one p1 anomaly → drops p1's unacked count to 2
    items, _ = await store.list_anomalies(target_profile="p1", limit=10, offset=0)
    await store.acknowledge(items[0].id)

    counts = await store.unacked_counts_by_profile(now - timedelta(days=7))
    assert counts == {"p1": 2, "p2": 1}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py -k unacked_counts`
Expected: FAIL — `unacked_counts_by_profile` undefined.

- [ ] **Step 3: Implement** — add to `src/autoagent/anomalies/store.py`:

```python
async def unacked_counts_by_profile(since) -> dict[str, int]:
    """Per profile: number of unacknowledged anomalies created since `since`.
    Feeds the health dashboard's anomaly signal."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(AnomalyRow.target_profile, func.count())
            .where(AnomalyRow.acknowledged == False)  # noqa: E712
            .where(AnomalyRow.created_at >= since)
            .group_by(AnomalyRow.target_profile)
        )
        return {profile: int(count) for profile, count in r.all()}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/anomalies/store.py tests/unit/test_anomaly_store.py; echo "EXIT=$?"
git add src/autoagent/anomalies/store.py tests/unit/test_anomaly_store.py
git commit -m "feat(health): add per-profile unacked anomaly counts"
```

---

## Task 3: `compute_health` pure function + schema

**Files:** Create `src/autoagent/health/__init__.py`, `src/autoagent/health/profile_health.py`; Modify `src/autoagent/models/api.py`; Test `tests/unit/test_compute_health.py`.

- [ ] **Step 1: Add the schema** to `src/autoagent/models/api.py` (append at end, `BaseModel`/`Field` already imported):

```python
class ProfileHealth(BaseModel):
    name: str
    platform: str
    status: str  # green | yellow | red | nodata
    success_rate: float | None = None
    total_runs: int = 0
    avg_duration_ms: float | None = None
    unacked_anomalies: int = 0
    devices_online: int | None = None
    devices_total: int | None = None
```

- [ ] **Step 2: Write the failing test** — create `tests/unit/test_compute_health.py`:

```python
from autoagent.health.profile_health import HealthMetrics, compute_health


def _m(**kw):
    base = dict(
        total_runs=10, success_rate=1.0, unacked_anomalies=0,
        devices_online=None, devices_total=None,
    )
    base.update(kw)
    return HealthMetrics(**base)


def test_nodata_when_no_runs():
    assert compute_health(_m(total_runs=0, success_rate=None)) == "nodata"


def test_success_rate_thresholds():
    assert compute_health(_m(success_rate=0.95)) == "green"
    assert compute_health(_m(success_rate=0.8)) == "yellow"
    assert compute_health(_m(success_rate=0.4)) == "red"


def test_anomaly_thresholds():
    assert compute_health(_m(unacked_anomalies=0)) == "green"
    assert compute_health(_m(unacked_anomalies=1)) == "yellow"
    assert compute_health(_m(unacked_anomalies=5)) == "red"


def test_device_signal_only_when_applicable():
    # all online → green
    assert compute_health(_m(devices_online=3, devices_total=3)) == "green"
    # some offline → yellow
    assert compute_health(_m(devices_online=1, devices_total=3)) == "yellow"
    # none online → red
    assert compute_health(_m(devices_online=0, devices_total=3)) == "red"
    # not applicable (non-android) → device signal ignored
    assert compute_health(_m(devices_online=None, devices_total=None)) == "green"


def test_worst_of_wins():
    # great success + great devices but 5 anomalies → red
    assert compute_health(_m(success_rate=1.0, unacked_anomalies=5, devices_online=3, devices_total=3)) == "red"
    # one yellow signal among greens → yellow
    assert compute_health(_m(success_rate=0.8, unacked_anomalies=0)) == "yellow"


def test_avg_duration_does_not_drive_color():
    # avg duration isn't even an input to compute_health — a slow profile with
    # otherwise-good signals is green.
    assert compute_health(_m(success_rate=1.0, unacked_anomalies=0)) == "green"
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_compute_health.py`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement** — create `src/autoagent/health/__init__.py` (empty) and `src/autoagent/health/profile_health.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

SUCCESS_RED = 0.5
SUCCESS_YELLOW = 0.9
ANOMALY_RED = 5
ANOMALY_YELLOW = 1

# Ordered worst → best for "worst-of" reduction and worst-first sorting.
_SEVERITY = {"red": 0, "yellow": 1, "green": 2, "nodata": 3}


@dataclass
class HealthMetrics:
    total_runs: int
    success_rate: float | None
    unacked_anomalies: int
    devices_online: int | None  # None = signal not applicable (non-android / unbound)
    devices_total: int | None


def _success_signal(rate: float | None) -> str:
    if rate is None:
        return "green"
    if rate < SUCCESS_RED:
        return "red"
    if rate < SUCCESS_YELLOW:
        return "yellow"
    return "green"


def _anomaly_signal(count: int) -> str:
    if count >= ANOMALY_RED:
        return "red"
    if count >= ANOMALY_YELLOW:
        return "yellow"
    return "green"


def _device_signal(online: int | None, total: int | None) -> str | None:
    if not total:  # None or 0 → not applicable
        return None
    if online == 0:
        return "red"
    if online < total:
        return "yellow"
    return "green"


def compute_health(m: HealthMetrics) -> str:
    """Worst-of the participating signals (success rate, unacked anomalies,
    device pool). Avg duration is display-only and deliberately not a signal.
    No terminal runs in the window → 'nodata' (no basis to judge)."""
    if m.total_runs == 0:
        return "nodata"
    signals = [_success_signal(m.success_rate), _anomaly_signal(m.unacked_anomalies)]
    dev = _device_signal(m.devices_online, m.devices_total)
    if dev is not None:
        signals.append(dev)
    return min(signals, key=lambda s: _SEVERITY[s])
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_compute_health.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/health/ src/autoagent/models/api.py tests/unit/test_compute_health.py; echo "EXIT=$?"
git add src/autoagent/health/__init__.py src/autoagent/health/profile_health.py src/autoagent/models/api.py tests/unit/test_compute_health.py
git commit -m "feat(health): add compute_health (worst-of) + ProfileHealth schema"
```

---

## Task 4: `list_profile_health` assembly

**Files:** Modify `src/autoagent/health/profile_health.py`; Test `tests/unit/test_list_profile_health.py`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_list_profile_health.py`:

```python
from datetime import datetime, timezone

import pytest

from autoagent.anomalies import store as anomaly_store
from autoagent.health.profile_health import list_profile_health
from autoagent.models.api import SampleResult
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.devices import upsert_discovered_device
from autoagent.storage.samples import upsert_sample


def _sample(sid, profile, status, ms):
    return SampleResult(
        id=sid, status=status, mode="gui_android", target_profile=profile,
        duration_ms=ms, ended_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_assembly_and_worst_first_order():
    await init_db()
    # healthy api profile
    save_profile_yaml("good", "name: good\nplatform: api\napi:\n  base_url: http://x\n  model: m\n  api_key: K\n")
    # unhealthy android profile (bound device offline + anomalies)
    save_profile_yaml(
        "bad",
        "name: bad\nplatform: gui_android\nserials: ['dev1']\n"
        "package: com.x\ninput_locator: {type: xpath, value: '//x'}\n",
    )
    for i in range(5):
        await upsert_sample("b", _sample(f"g{i}", "good", "done", 100))
    await upsert_sample("b", _sample("bad1", "bad", "failed", None))
    for i in range(5):
        await anomaly_store.record_anomaly(
            type="duration", batch_id="b", sample_id=f"a{i}", target_profile="bad",
            device_serial="dev1", summary="x", detail={},
        )
    await upsert_discovered_device(
        serial="dev1", model="m", android_version="14",
        adb_keyboard_installed=False, adb_keyboard_enabled=False, online=False,
        seen_at=datetime.now(timezone.utc),
    )

    health = await list_profile_health()
    by_name = {h.name: h for h in health}
    assert by_name["good"].status == "green"
    assert by_name["good"].success_rate == 1.0
    assert by_name["bad"].status == "red"
    assert by_name["bad"].unacked_anomalies == 5
    assert by_name["bad"].devices_online == 0 and by_name["bad"].devices_total == 1
    # worst-first: bad (red) before good (green)
    assert [h.name for h in health].index("bad") < [h.name for h in health].index("good")
```

Adapt the two `save_profile_yaml` bodies if the profile schema rejects them — the goal is one valid `api` profile and one valid `gui_android` profile with `serials: ['dev1']`. Check `profiles/schemas.py` for required fields and adjust minimally.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_list_profile_health.py`
Expected: FAIL — `list_profile_health` undefined.

- [ ] **Step 3: Implement** — append to `src/autoagent/health/profile_health.py` (add imports at top of file):

```python
from datetime import datetime, timedelta, timezone

from autoagent.anomalies import store as anomaly_store
from autoagent.models.api import ProfileHealth
from autoagent.profiles.registry import list_profile_names, load_profile
from autoagent.storage.devices import list_devices
from autoagent.storage.samples import avg_duration_by_profile, success_stats_by_profile

WINDOW_DAYS = 7
_ANDROID_PLATFORMS = {"gui_android", "agent_android"}


async def list_profile_health(now: datetime | None = None) -> list[ProfileHealth]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)

    success = await success_stats_by_profile(since)
    durations = await avg_duration_by_profile(since=since)
    anomalies = await anomaly_store.unacked_counts_by_profile(since)
    devices = {d.serial: d for d in await list_devices()}

    out: list[ProfileHealth] = []
    for name in list_profile_names():
        profile = load_profile(name)
        if profile is None:
            continue
        done, total = success.get(name, (0, 0))
        rate = (done / total) if total else None

        serials: list[str] = []
        online_ct: int | None = None
        total_ct: int | None = None
        if profile.platform in _ANDROID_PLATFORMS:
            serial = getattr(profile, "serial", None)
            serials = list(getattr(profile, "serials", None) or [])
            if serial and serial not in serials:
                serials = [serial, *serials]
            if serials:
                total_ct = len(serials)
                online_ct = sum(1 for s in serials if devices.get(s) and devices[s].online)

        metrics = HealthMetrics(
            total_runs=total,
            success_rate=rate,
            unacked_anomalies=anomalies.get(name, 0),
            devices_online=online_ct,
            devices_total=total_ct,
        )
        out.append(
            ProfileHealth(
                name=name,
                platform=profile.platform,
                status=compute_health(metrics),
                success_rate=rate,
                total_runs=total,
                avg_duration_ms=durations.get(name),
                unacked_anomalies=anomalies.get(name, 0),
                devices_online=online_ct,
                devices_total=total_ct,
            )
        )

    out.sort(key=lambda h: (_SEVERITY[h.status], h.name))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_list_profile_health.py`
Expected: PASS. (If profile YAML validation fails, adjust the two test fixtures per Step 1's note.)

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/health/profile_health.py tests/unit/test_list_profile_health.py; echo "EXIT=$?"
git add src/autoagent/health/profile_health.py tests/unit/test_list_profile_health.py
git commit -m "feat(health): assemble per-profile health from the four signals"
```

---

## Task 5: `GET /profiles/health` endpoint

**Files:** Modify `src/autoagent/api/profiles.py`; Test `tests/integration/test_profile_health_endpoint.py`.

- [ ] **Step 1: Write the failing test** — create `tests/integration/test_profile_health_endpoint.py`. Copy the `client`/`_login` fixtures from `tests/integration/test_anomalies_endpoints.py`, then:

```python
@pytest.mark.asyncio
async def test_profile_health_endpoint(client):
    from autoagent.profiles.registry import save_profile_yaml
    from autoagent.storage.samples import upsert_sample
    from autoagent.models.api import SampleResult
    from datetime import datetime, timezone

    h = await _login(client)
    save_profile_yaml("ph", "name: ph\nplatform: api\napi:\n  base_url: http://x\n  model: m\n  api_key: K\n")
    await upsert_sample(
        "b",
        SampleResult(id="s1", status="done", mode="api", target_profile="ph",
                     duration_ms=100, ended_at=datetime.now(timezone.utc)),
    )

    r = await client.get("/api/v1/profiles/health", headers=h)
    assert r.status_code == 200
    rows = {row["name"]: row for row in r.json()}
    assert rows["ph"]["status"] == "green"
    assert rows["ph"]["total_runs"] == 1
    assert rows["ph"]["success_rate"] == 1.0


@pytest.mark.asyncio
async def test_profile_health_requires_auth(client):
    r = await client.get("/api/v1/profiles/health")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_profile_health_endpoint.py`
Expected: FAIL — 404.

- [ ] **Step 3: Implement** — in `src/autoagent/api/profiles.py`, add the import and route. Add near the other imports: `from autoagent.health.profile_health import list_profile_health` and `from autoagent.models.api import ProfileHealth`. Then add the route **before** the `@router.get("/{name}")` route (so `/health` isn't captured as a profile name):

```python
@router.get("/health", response_model=list[ProfileHealth])
async def profiles_health() -> list[ProfileHealth]:
    return await list_profile_health()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_profile_health_endpoint.py`
Expected: PASS. (If `/health` is still captured by `/{name}`, confirm the route is registered above `@router.get("/{name}")` in the file.)

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/api/profiles.py tests/integration/test_profile_health_endpoint.py; echo "EXIT=$?"
git add src/autoagent/api/profiles.py tests/integration/test_profile_health_endpoint.py
git commit -m "feat(health): add GET /profiles/health endpoint"
```

---

## Task 6: Frontend data layer

**Files:** Modify `web/src/types/api.ts`; Create `web/src/api/profileHealth.ts`, `web/src/api/profileHealth.test.ts`.

- [ ] **Step 1: Add types** to `web/src/types/api.ts`:

```ts
export type HealthStatus = 'green' | 'yellow' | 'red' | 'nodata'

export interface ProfileHealth {
  name: string
  platform: string
  status: HealthStatus
  success_rate: number | null
  total_runs: number
  avg_duration_ms: number | null
  unacked_anomalies: number
  devices_online: number | null
  devices_total: number | null
}
```

- [ ] **Step 2: Write the failing test** — create `web/src/api/profileHealth.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { summarizeHealth } from './profileHealth'
import type { ProfileHealth } from '../types/api'

function row(status: ProfileHealth['status']): ProfileHealth {
  return {
    name: 'p',
    platform: 'api',
    status,
    success_rate: 1,
    total_runs: 1,
    avg_duration_ms: 100,
    unacked_anomalies: 0,
    devices_online: null,
    devices_total: null,
  }
}

describe('summarizeHealth', () => {
  it('counts by status', () => {
    expect(summarizeHealth([row('green'), row('green'), row('red'), row('nodata')])).toEqual({
      green: 2,
      yellow: 0,
      red: 1,
      nodata: 1,
    })
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/api/profileHealth.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement** — create `web/src/api/profileHealth.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { HealthStatus, ProfileHealth } from '../types/api'
import { client } from './client'

export function useProfileHealth() {
  return useQuery({
    queryKey: ['profiles', 'health'],
    queryFn: async () => (await client.get<ProfileHealth[]>('/profiles/health')).data,
  })
}

export function summarizeHealth(rows: ProfileHealth[]): Record<HealthStatus, number> {
  const out: Record<HealthStatus, number> = { green: 0, yellow: 0, red: 0, nodata: 0 }
  for (const r of rows) out[r.status] += 1
  return out
}
```

- [ ] **Step 5: Run to verify it passes + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/api/profileHealth.test.ts && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean.

- [ ] **Step 6: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/types/api.ts web/src/api/profileHealth.ts web/src/api/profileHealth.test.ts
git commit -m "feat(web): add the profile-health data layer"
```

---

## Task 7: Health page + route + nav

**Files:** Create `web/src/pages/Profiles/Health.tsx`; Modify `web/src/App.tsx`, `web/src/components/AppLayout.tsx`; Test `web/src/pages/Profiles/Health.test.tsx`.

- [ ] **Step 1: Write the failing test** — create `web/src/pages/Profiles/Health.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { ProfileHealth } from '../../types/api'
import { Health } from './Health'

const useProfileHealth = vi.fn()

vi.mock('../../api/profileHealth', async () => {
  const actual = await vi.importActual<typeof import('../../api/profileHealth')>(
    '../../api/profileHealth',
  )
  return { ...actual, useProfileHealth: () => useProfileHealth() }
})

function row(over: Partial<ProfileHealth> & { name: string }): ProfileHealth {
  return {
    platform: 'api',
    status: 'green',
    success_rate: 1,
    total_runs: 5,
    avg_duration_ms: 100,
    unacked_anomalies: 0,
    devices_online: null,
    devices_total: null,
    ...over,
  }
}

function AnomaliesStub() {
  const loc = useLocation()
  return <div>anomalies-page{loc.search}</div>
}

describe('Health', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders cards worst-first with a summary bar', async () => {
    useProfileHealth.mockReturnValue({
      data: [
        row({ name: 'bad', status: 'red', unacked_anomalies: 6, success_rate: 0.4 }),
        row({ name: 'good', status: 'green' }),
      ],
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    await waitFor(() => expect(screen.getByText('bad')).toBeInTheDocument())
    expect(screen.getByText('good')).toBeInTheDocument()
    // summary bar mentions the red count
    expect(screen.getByText(/1 异常/)).toBeInTheDocument()
  })

  it('clicks the anomaly count through to the anomaly center filtered by profile', async () => {
    useProfileHealth.mockReturnValue({
      data: [row({ name: 'bad', status: 'red', unacked_anomalies: 3 })],
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
        <Route path="/system/anomalies" element={<AnomaliesStub />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    await userEvent.click(await screen.findByText(/异常 3/))
    expect(await screen.findByText('anomalies-page?target_profile=bad')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Profiles/Health.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the page** — create `web/src/pages/Profiles/Health.tsx`:

```tsx
import { Card, Col, Row, Segmented, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { summarizeHealth, useProfileHealth } from '../../api/profileHealth'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import type { HealthStatus, ProfileHealth } from '../../types/api'
import { formatDurationMs } from '../../utils/duration'

const STATUS_META: Record<HealthStatus, { color: string; label: string }> = {
  red: { color: '#cf1322', label: '异常' },
  yellow: { color: '#d48806', label: '警告' },
  green: { color: '#389e0d', label: '健康' },
  nodata: { color: '#8c8c8c', label: '无数据' },
}

function HealthCard({ row }: { row: ProfileHealth }) {
  const navigate = useNavigate()
  const meta = STATUS_META[row.status]
  return (
    <Card size="small" styles={{ body: { padding: 12 } }}>
      <Space style={{ marginBottom: 8 }} align="center">
        <span
          style={{ width: 10, height: 10, borderRadius: '50%', background: meta.color, display: 'inline-block' }}
        />
        <a onClick={() => navigate(`/profiles/${row.name}`)} style={{ fontWeight: 600 }}>
          {row.name}
        </a>
        <Tag>{row.platform}</Tag>
      </Space>
      <div style={{ fontSize: 13, lineHeight: 1.9 }}>
        <div>
          成功率{' '}
          {row.success_rate === null ? '—' : `${Math.round(row.success_rate * 100)}%`}{' '}
          <Typography.Text type="secondary">({row.total_runs} 次)</Typography.Text>
        </div>
        <div>耗时 {row.avg_duration_ms === null ? '—' : formatDurationMs(row.avg_duration_ms)}</div>
        <div>
          <a onClick={() => navigate(`/system/anomalies?target_profile=${encodeURIComponent(row.name)}`)}>
            异常 {row.unacked_anomalies}
          </a>
        </div>
        <div>
          设备{' '}
          {row.devices_total === null ? '—' : `${row.devices_online}/${row.devices_total}`}
        </div>
      </div>
    </Card>
  )
}

export function Health() {
  const { data, isLoading, isError, refetch } = useProfileHealth()
  const [unhealthyOnly, setUnhealthyOnly] = useState(false)

  const rows = useMemo(() => {
    const all = data ?? []
    return unhealthyOnly ? all.filter((r) => r.status === 'red' || r.status === 'yellow') : all
  }, [data, unhealthyOnly])

  const summary = useMemo(() => summarizeHealth(data ?? []), [data])

  if (isError) return <ErrorState title="加载失败" onRetry={() => refetch()} />

  return (
    <div>
      <PageHeader title="Profile 健康" subtitle="近 7 天每个配置档的健康快照" />
      <Space style={{ marginBottom: 12 }} wrap>
        <Typography.Text type="secondary">
          {summary.green} 健康 · {summary.yellow} 警告 · {summary.red} 异常 · {summary.nodata} 无数据
        </Typography.Text>
        <Segmented
          value={unhealthyOnly ? 'unhealthy' : 'all'}
          onChange={(v) => setUnhealthyOnly(v === 'unhealthy')}
          options={[
            { value: 'all', label: '全部' },
            { value: 'unhealthy', label: '只看非健康' },
          ]}
        />
      </Space>
      {!isLoading && rows.length === 0 ? (
        <EmptyState title="没有配置档" description="先创建配置档并运行批次后再来看健康度。" />
      ) : (
        <Row gutter={[12, 12]}>
          {rows.map((r) => (
            <Col key={r.name} xs={24} sm={12} md={8} lg={6}>
              <HealthCard row={r} />
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Add the route** in `web/src/App.tsx` — import `Health` and add `<Route path="profiles/health" element={<Health />} />` **before** the `profiles/:name` route (so `health` isn't captured as a profile name):

```tsx
import { Health } from './pages/Profiles/Health'
...
          <Route path="profiles" element={<ProfileList />} />
          <Route path="profiles/health" element={<Health />} />
          <Route path="profiles/builder" element={<BuilderHub />} />
```

Confirm placement: `profiles/health` must be registered before `profiles/:name`.

- [ ] **Step 5: Add the nav entry** in `web/src/components/AppLayout.tsx` — in the 资源 group's `items`, after 配置档 Profiles: `{ key: '/profiles/health', label: 'Profile 健康 Health', icon: <HeartOutlined /> }`. Import `HeartOutlined` from `@ant-design/icons`.

- [ ] **Step 6: Run to verify it passes + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Profiles/Health.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean. (If `Segmented`/`Card styles` type errors appear, they don't here — AntD 5 supports `styles.body`. If the AntD version rejects `styles`, use `bodyStyle={{ padding: 12 }}`.)

- [ ] **Step 7: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/Profiles/Health.tsx src/pages/Profiles/Health.test.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Profiles/Health.tsx web/src/pages/Profiles/Health.test.tsx web/src/App.tsx web/src/components/AppLayout.tsx
git commit -m "feat(web): add the Profile Health dashboard page, route, and nav"
```

---

## Task 8: Anomaly Center URL `target_profile` prefilter

**Files:** Modify `web/src/pages/System/Anomalies.tsx`; Test `web/src/pages/System/Anomalies.test.tsx` (extend).

- [ ] **Step 1: Write the failing test** — add to `web/src/pages/System/Anomalies.test.tsx` a case asserting the page reads `?target_profile=` from the URL and filters. Add a profile-filter assertion:

```tsx
it('prefills the profile filter from the URL target_profile query', async () => {
  useAnomalies.mockReturnValue({
    data: { items: [], total: 0 },
    isLoading: false,
    isError: false,
  })
  renderWithProviders(
    <Routes>
      <Route path="/system/anomalies" element={<Anomalies />} />
    </Routes>,
    { initialPath: '/system/anomalies?target_profile=qwen' },
  )
  // useAnomalies must have been called with a filter carrying target_profile=qwen
  await waitFor(() => {
    const calledWith = useAnomalies.mock.calls.at(-1)?.[0]
    expect(calledWith).toMatchObject({ target_profile: 'qwen' })
  })
})
```

Note: the existing `Anomalies` test mocks `useAnomalies` as `(...a) => useAnomalies(...a)` — confirm it forwards args so `.mock.calls` captures the filter object. If the current mock is arg-less, update it to forward args (and re-run the existing tests to confirm still green).

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/System/Anomalies.test.tsx`
Expected: FAIL — the new test (target_profile not applied).

- [ ] **Step 3: Implement** — in `web/src/pages/System/Anomalies.tsx`, read `useSearchParams` and fold `target_profile` into the filters. Add `import { useSearchParams } from 'react-router-dom'`, then:

```tsx
  const [params] = useSearchParams()
  const targetProfile = params.get('target_profile') ?? undefined
```

and include it in the `filters` useMemo (add `target_profile: targetProfile` to the object and `targetProfile` to the dep array). Verify the api layer's `buildAnomalyParams` already forwards `target_profile` (it does — Task 9 of the anomaly-center plan defined it). Optionally show a dismissible `Tag` when a profile filter is active (`当前筛选: <profile> ✕` clearing to `/system/anomalies`) — keep minimal: just applying the filter satisfies the spec.

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/System/Anomalies.test.tsx`
Expected: PASS (all Anomalies tests).

- [ ] **Step 5: Typecheck + lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/System/Anomalies.tsx web/src/pages/System/Anomalies.test.tsx
git commit -m "feat(web): Anomaly Center prefills its profile filter from the URL"
```

---

## Task 9: Full verification + docs

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1: Backend fast suite + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run ruff check . && uv run pytest -q -m "not playwright and not android and not slow"`
Expected: lint clean, all tests pass.

- [ ] **Step 2: Frontend full suite + typecheck + lint + build**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run && pnpm build`
Expected: all green.

- [ ] **Step 3: Add the CLAUDE.md changelog entry** — a new bullet documenting the profile health dashboard (four signals, 7-day window, worst-of status, endpoint, page, nav, the anomaly-center prefilter), referencing the spec + this plan.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the profile health dashboard feature"
```

- [ ] **Step 5: Push + verify CI** — push and confirm CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`.

---

## Self-Review

**1. Spec coverage:**
- Four signals (success/duration/anomalies/devices) → Tasks 1, 2, 4. ✓
- 7-day window → Tasks 1, 2, 4 (`since`). ✓
- Worst-of status + nodata → Task 3 (`compute_health`). ✓
- Avg duration display-only (not a color driver) → Task 3 (not a `compute_health` input) + Task 7 (shown). ✓
- Endpoint → Task 5. ✓
- `ProfileHealth` schema → Task 3. ✓
- Card grid, worst-first, summary bar, unhealthy-only toggle → Task 7. ✓
- Click-throughs (anomaly→center, name→edit, device count) → Task 7. ✓
- Nav entry → Task 7. ✓
- Anomaly Center URL prefilter → Task 8. ✓
- Testing (pure fn, queries, assembly, endpoint, hooks, page, prefilter) → each task + Task 9. ✓

**2. Placeholder scan:** No TBD/TODO. Two "adapt if the profile schema rejects the YAML / if the AntD version rejects `styles`" notes are deliberate fallbacks naming the exact alternative, not vague hand-waves.

**3. Type consistency:** `HealthMetrics` fields (`total_runs/success_rate/unacked_anomalies/devices_online/devices_total`) identical across Tasks 3 & 4. `ProfileHealth` fields identical across Task 3 (schema), Task 4 (construction), Task 6 (TS mirror). `compute_health` returns the same 4 status strings consumed by `_SEVERITY` sort (Task 4) and `STATUS_META` (Task 7). `summarizeHealth` shape matches Task 6 test + Task 7 usage. `success_stats_by_profile` returns `{profile: (done, total)}` consumed identically in Task 4. `unacked_counts_by_profile` returns `{profile: int}` consumed in Task 4.
