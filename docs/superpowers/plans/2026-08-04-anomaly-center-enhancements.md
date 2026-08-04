# Anomaly Center Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a time-range filter, an idempotent historical duration-anomaly backfill, and an opt-in periodic DingTalk digest to the anomaly center.

**Architecture:** Extends the existing `anomalies/store.py` + `api/anomalies.py` + `pages/System/Anomalies.tsx`. Backfill is a new `anomalies/backfill.py` (pure point-in-time slide over `storage/samples.py::timed_samples_for_profile`, dedup via `store.existing_duration_sample_ids`). Digest is a new `anomalies/digest.py` (pure markdown builder) + a `run_digest_loop` in `maintenance/scheduler.py` wired into `main.py`'s lifespan, gated by a new `DingTalkNotificationConfig.digest_interval_hours` and stateful via an `anomaly_digest_state` kv key.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (SQLite), `uv`; React 18 + TS + AntD 5, TanStack Query, Vitest.

---

## Context an implementer needs

- **`anomalies/store.py`** already has `record_anomaly(*, type, batch_id, sample_id, target_profile, device_serial, summary, detail)`, `list_anomalies(*, type=None, target_profile=None, acknowledged=None, limit, offset) -> (list[AnomalyRecord], int)`, `acknowledge`, `count_unacknowledged`, `unacked_counts_by_profile`, `delete_for_batch`. It imports `from datetime import datetime, timezone`, `from sqlalchemy import delete, func, select`, `AnomalyRow` (= `Anomaly` ORM), `_row_to_record`.
- **`Anomaly` columns** (`models/db.py`): `id, type, batch_id, sample_id, target_profile, device_serial, summary, detail_json, acknowledged, acknowledged_at, created_at`.
- **`Sample` columns**: `batch_id, id, status, duration_ms (nullable), target_profile, ended_at (nullable), metadata_json (nullable)`. No `device_serial` column — it lives in `metadata_json`'s `device_serial` key (the live hook reads `result.metadata.get("device_serial")`).
- **Duration detector** (`anomalies/duration_detector.py`): `evaluate_duration(value: int, history: list[int]) -> dict | None` (IQR fences, returns `None` when `len(history) < MIN_HISTORY` (20) or value is inside the fences), `MIN_HISTORY = 20`, `_format_summary(verdict: dict) -> str` (builds the human summary like `耗时 8.2s，高于 P75+1.5·IQR 阈值 6.1s`).
- **DingTalk**: `notifications/dingtalk.py::send_markdown(*, webhook_url, secret, title, text, at_mobiles=None, at_all=False) -> SendResult` (`.ok` bool). `DingTalkNotificationConfig` (`models/api.py`) has `enabled, webhook_url, secret, ..., app_base_url`. Config persisted under kv key `"notifications"` (`GET/PUT /api/v1/config/notifications`).
- **kv config**: `storage/configs.py::get_config(key) -> dict|None`, `put_config(key, value)`. Used for `notification_state` in `rules.py`.
- **Scheduler pattern**: `maintenance/scheduler.py::run_backup_loop()` — `await asyncio.sleep(_BACKUP_STARTUP_DELAY_SEC)`, then `while True:` read-config/tick/sleep, each tick guarded so a failure doesn't kill the loop. Wired in `main.py` lifespan: `backup_task = asyncio.create_task(run_backup_loop())` added to `background_tasks`.
- **Config page** (`web/src/pages/Config.tsx`): a `notifyForm` (AntD Form) bound to `useNotifications()` data via `notifyForm.setFieldsValue`. `RuleSection` groups `Form.Item`s. There's a `立即备份` button around line 430 (`handleBackup`) — model the backfill button on it. `web/src/api/config.ts` has `useNotifications`/save mutations and a backup-trigger mutation to model the backfill hook on.
- **Anomaly api/page**: `web/src/api/anomalies.ts` has `AnomalyFilters` (`type?, target_profile?, acknowledged?, limit, offset`), `buildAnomalyParams(f)`, `useAnomalies(filters)`. `web/src/pages/System/Anomalies.tsx` builds `filters` in a `useMemo` and renders a `Select` + `Segmented` filter row.
- **Tests**: `pytest-asyncio` auto mode; storage/unit tests `await init_db()` first. Integration tests copy the `client`/`_login` fixtures from `tests/integration/test_anomalies_endpoints.py`. Run `uv run pytest -q <path>`; lint `uv run ruff check <files>; echo EXIT=$?`. Frontend: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run <path>`, `pnpm exec tsc --noEmit`, `pnpm lint`. pnpm cwd resets → prefix `cd .../web &&`.

---

## File Structure

- Modify `src/autoagent/anomalies/store.py` (add `created_after`/`created_before` to `list_anomalies`; add `existing_duration_sample_ids`, `anomalies_created_since`)
- Modify `src/autoagent/storage/samples.py` (add `TimedSample` + `timed_samples_for_profile`)
- Create `src/autoagent/anomalies/backfill.py` (`BackfillResult`, `backfill_duration_anomalies`)
- Create `src/autoagent/anomalies/digest.py` (`build_digest_markdown`)
- Modify `src/autoagent/api/anomalies.py` (time params on `GET`; `POST /backfill`)
- Modify `src/autoagent/models/api.py` (`DingTalkNotificationConfig.digest_interval_hours`; `BackfillResult` response schema if needed — use a plain dict)
- Modify `src/autoagent/maintenance/scheduler.py` (`run_digest_loop`) + `src/autoagent/main.py` (wire it)
- Frontend: `web/src/api/anomalies.ts` (time fields + backfill hook), `web/src/pages/System/Anomalies.tsx` (RangePicker), `web/src/pages/Config.tsx` (backfill button + digest field), `web/src/api/config.ts` (backfill mutation if not present)
- Tests: `tests/unit/test_anomaly_store.py` (extend), `tests/unit/test_anomaly_backfill.py`, `tests/unit/test_anomaly_digest.py`, `tests/unit/test_digest_loop.py`, `tests/integration/test_anomalies_endpoints.py` (extend); frontend `Anomalies.test.tsx`/`Config.test.tsx` extensions.

---

## Task 1: Time-range filter in the store + endpoint

**Files:** Modify `src/autoagent/anomalies/store.py`, `src/autoagent/api/anomalies.py`; Test `tests/unit/test_anomaly_store.py`, `tests/integration/test_anomalies_endpoints.py`.

- [ ] **Step 1: Write the failing store test** — append to `tests/unit/test_anomaly_store.py`:

```python
@pytest.mark.asyncio
async def test_list_anomalies_time_filter():
    from datetime import datetime, timedelta, timezone

    await init_db()
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    now = datetime.now(timezone.utc)
    # created_after in the future → excludes everything
    _, after_future = await store.list_anomalies(
        created_after=now + timedelta(hours=1), limit=10, offset=0
    )
    assert after_future == 0
    # created_after in the past → includes it
    _, after_past = await store.list_anomalies(
        created_after=now - timedelta(hours=1), limit=10, offset=0
    )
    assert after_past == 1
    # created_before in the past → excludes it
    _, before_past = await store.list_anomalies(
        created_before=now - timedelta(hours=1), limit=10, offset=0
    )
    assert before_past == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py -k time_filter`
Expected: FAIL — `list_anomalies` got an unexpected keyword `created_after`.

- [ ] **Step 3: Implement in the store** — in `src/autoagent/anomalies/store.py`, change `list_anomalies`'s signature and add the two conditions:

```python
async def list_anomalies(
    *,
    type: str | None = None,
    target_profile: str | None = None,
    acknowledged: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AnomalyRecord], int]:
    sm = get_sessionmaker()
    async with sm() as s:
        conds = []
        if type is not None:
            conds.append(AnomalyRow.type == type)
        if target_profile is not None:
            conds.append(AnomalyRow.target_profile == target_profile)
        if acknowledged is not None:
            conds.append(AnomalyRow.acknowledged == acknowledged)
        if created_after is not None:
            conds.append(AnomalyRow.created_at >= created_after)
        if created_before is not None:
            conds.append(AnomalyRow.created_at <= created_before)
        # ... rest unchanged (total count + rows query using *conds) ...
```

Keep the existing `total`/`rows` query body below the conds exactly as-is.

- [ ] **Step 4: Run to verify the store test passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py`
Expected: PASS.

- [ ] **Step 5: Write the failing endpoint test** — append to `tests/integration/test_anomalies_endpoints.py`:

```python
@pytest.mark.asyncio
async def test_list_anomalies_time_params(client):
    h = await _login(client)
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    # far-future created_after → empty
    r = await client.get("/api/v1/anomalies?created_after=2099-01-01T00:00:00Z", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 0
    # past created_after → present
    r = await client.get("/api/v1/anomalies?created_after=2000-01-01T00:00:00Z", headers=h)
    assert r.json()["total"] == 1
```

- [ ] **Step 6: Implement in the endpoint** — in `src/autoagent/api/anomalies.py`, add the two params to `list_anomalies` and pass them through. Add `from datetime import datetime` at the top:

```python
@router.get("", response_model=AnomalyListResponse)
async def list_anomalies(
    type: str | None = None,
    target_profile: str | None = None,
    acknowledged: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AnomalyListResponse:
    items, total = await store.list_anomalies(
        type=type,
        target_profile=target_profile,
        acknowledged=acknowledged,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    return AnomalyListResponse(items=items, total=total)
```

- [ ] **Step 7: Run both test files to verify pass**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py tests/integration/test_anomalies_endpoints.py`
Expected: PASS.

- [ ] **Step 8: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/anomalies/store.py src/autoagent/api/anomalies.py tests/unit/test_anomaly_store.py tests/integration/test_anomalies_endpoints.py; echo "EXIT=$?"
git add src/autoagent/anomalies/store.py src/autoagent/api/anomalies.py tests/unit/test_anomaly_store.py tests/integration/test_anomalies_endpoints.py
git commit -m "feat(anomalies): filter the anomaly list by created_at time range"
```

---

## Task 2: Time-range filter frontend (RangePicker)

**Files:** Modify `web/src/api/anomalies.ts`, `web/src/pages/System/Anomalies.tsx`; Test `web/src/pages/System/Anomalies.test.tsx`.

- [ ] **Step 1: Extend the api layer** — in `web/src/api/anomalies.ts`, add `created_after?`/`created_before?` to `AnomalyFilters` and forward them in `buildAnomalyParams`:

```ts
export interface AnomalyFilters {
  type?: AnomalyType
  target_profile?: string
  acknowledged?: boolean
  created_after?: string
  created_before?: string
  limit: number
  offset: number
}

export function buildAnomalyParams(f: AnomalyFilters): Record<string, string | number | boolean> {
  const p: Record<string, string | number | boolean> = { limit: f.limit, offset: f.offset }
  if (f.type) p.type = f.type
  if (f.target_profile) p.target_profile = f.target_profile
  if (f.acknowledged !== undefined) p.acknowledged = f.acknowledged
  if (f.created_after) p.created_after = f.created_after
  if (f.created_before) p.created_before = f.created_before
  return p
}
```

- [ ] **Step 2: Write the failing page test** — add to `web/src/pages/System/Anomalies.test.tsx` a test that selecting a preset range feeds the params. Because AntD `RangePicker` interaction is fiddly in jsdom, test via a preset click. Add:

```tsx
it('feeds a selected time range into the anomaly query', async () => {
  useAnomalies.mockReturnValue({ data: { items: [], total: 0 }, isLoading: false, isError: false })
  renderWithProviders(
    <Routes>
      <Route path="/system/anomalies" element={<Anomalies />} />
    </Routes>,
    { initialPath: '/system/anomalies' },
  )
  // open the range picker and pick the "最近 24 小时" preset
  await userEvent.click(screen.getByPlaceholderText('开始时间'))
  await userEvent.click(await screen.findByText('最近 24 小时'))
  await waitFor(() => {
    const calledWith = useAnomalies.mock.calls.at(-1)?.[0]
    expect(calledWith?.created_after).toBeTruthy()
  })
})
```

Note: if the preset label text or placeholder differs from what AntD renders, adjust the query to match the actual DOM (inspect via `screen.debug()` once). The essential assertion is that after choosing a preset, `useAnomalies` is called with a truthy `created_after`.

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/System/Anomalies.test.tsx`
Expected: FAIL (no RangePicker yet).

- [ ] **Step 4: Implement the RangePicker** — in `web/src/pages/System/Anomalies.tsx`:
  - Import `DatePicker` from antd and `dayjs` (already a dependency): `import { DatePicker } from 'antd'` (add to the existing antd import), `import dayjs, { Dayjs } from 'dayjs'`.
  - Add state: `const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null)`.
  - Add `created_after`/`created_before` to the `filters` useMemo (derived from `range`) and its deps:
    ```tsx
    const filters = useMemo(
      () => ({
        type: typeFilter,
        target_profile: targetProfile,
        acknowledged: showAll ? undefined : false,
        created_after: range?.[0]?.toISOString(),
        created_before: range?.[1]?.toISOString(),
        limit: pageSize,
        offset: (page - 1) * pageSize,
      }),
      [typeFilter, targetProfile, showAll, range, page],
    )
    ```
  - Render a `DatePicker.RangePicker` in the filter `Space` with presets:
    ```tsx
    <DatePicker.RangePicker
      showTime
      value={range}
      onChange={(v) => {
        setRange(v as [Dayjs, Dayjs] | null)
        setPage(1)
      }}
      presets={[
        { label: '最近 1 小时', value: [dayjs().add(-1, 'h'), dayjs()] },
        { label: '最近 24 小时', value: [dayjs().add(-24, 'h'), dayjs()] },
        { label: '最近 7 天', value: [dayjs().add(-7, 'd'), dayjs()] },
        { label: '最近 30 天', value: [dayjs().add(-30, 'd'), dayjs()] },
      ]}
    />
    ```

- [ ] **Step 5: Run test + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/System/Anomalies.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean. (If the test's DOM queries don't match AntD's rendered structure, adjust them per Step 2's note until green — the implementation is correct if `filters.created_after` becomes truthy on preset selection.)

- [ ] **Step 6: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/System/Anomalies.tsx src/pages/System/Anomalies.test.tsx src/api/anomalies.ts
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/api/anomalies.ts web/src/pages/System/Anomalies.tsx web/src/pages/System/Anomalies.test.tsx
git commit -m "feat(web): add a time-range picker to the anomaly center"
```

---

## Task 3: Backfill support queries

**Files:** Modify `src/autoagent/anomalies/store.py`, `src/autoagent/storage/samples.py`; Test `tests/unit/test_anomaly_store.py`, `tests/unit/test_profile_health_queries.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_anomaly_store.py`:

```python
@pytest.mark.asyncio
async def test_existing_duration_sample_ids():
    await init_db()
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    await store.record_anomaly(
        type="anr", batch_id="b", sample_id="s2", target_profile="p",
        device_serial=None, summary="y", detail={},
    )
    ids = await store.existing_duration_sample_ids()
    assert ids == {"s1"}  # anr's s2 excluded
```

And append to `tests/unit/test_profile_health_queries.py`:

```python
@pytest.mark.asyncio
async def test_timed_samples_for_profile_ordered_with_device():
    from datetime import datetime, timedelta, timezone

    from autoagent.storage.samples import timed_samples_for_profile

    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample(
        "b",
        SampleResult(id="s2", status="done", mode="api", target_profile="p",
                     duration_ms=200, ended_at=now, metadata={"device_serial": "d9"}),
    )
    await upsert_sample(
        "b",
        SampleResult(id="s1", status="done", mode="api", target_profile="p",
                     duration_ms=100, ended_at=now - timedelta(minutes=5)),
    )
    # a null-duration sample must be excluded
    await upsert_sample(
        "b", SampleResult(id="s3", status="failed", mode="api", target_profile="p")
    )
    rows = await timed_samples_for_profile("p")
    assert [r.sample_id for r in rows] == ["s1", "s2"]  # ended_at ascending
    assert rows[0].duration_ms == 100 and rows[0].device_serial is None
    assert rows[1].device_serial == "d9"


@pytest.mark.asyncio
async def test_distinct_sample_profiles():
    from autoagent.storage.samples import distinct_sample_profiles

    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="a", status="done", mode="api",
                                          target_profile="p1", duration_ms=100, ended_at=now))
    await upsert_sample("b", SampleResult(id="c", status="failed", mode="api",
                                          target_profile="p2"))  # no duration → excluded
    assert set(await distinct_sample_profiles()) == {"p1"}
```

(`test_profile_health_queries.py` already imports `datetime`/`timezone` at the top — reuse them.)

(`test_profile_health_queries.py` already imports `SampleResult`, `upsert_sample`, `init_db` — verify and reuse.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py -k existing_duration tests/unit/test_profile_health_queries.py -k timed_samples`
Expected: FAIL (both undefined).

- [ ] **Step 3: Implement `existing_duration_sample_ids`** — add to `src/autoagent/anomalies/store.py`:

```python
async def existing_duration_sample_ids() -> set[str]:
    """Sample ids that already have a type='duration' anomaly — the dedup key
    for backfill (each sample yields at most one duration anomaly)."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(AnomalyRow.sample_id).where(AnomalyRow.type == "duration").distinct()
        )
        return {sid for (sid,) in r.all()}
```

- [ ] **Step 4: Implement `timed_samples_for_profile`** — add to `src/autoagent/storage/samples.py` (it already imports `json`, `select`, `SampleRow`; add `from dataclasses import dataclass` at the top if not present):

```python
@dataclass
class TimedSample:
    sample_id: str
    batch_id: str
    duration_ms: int
    device_serial: str | None


async def distinct_sample_profiles() -> list[str]:
    """Every target_profile that has at least one timed sample — the set
    backfill iterates (sample-derived, not on-disk, so it covers profiles
    whose YAML was deleted)."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(SampleRow.target_profile)
            .where(SampleRow.duration_ms.is_not(None))
            .distinct()
        )
        return [p for (p,) in r.all()]


async def timed_samples_for_profile(profile: str) -> list[TimedSample]:
    """A profile's timed samples (duration_ms not null), oldest first, with
    device_serial parsed best-effort from metadata_json. For backfill's
    point-in-time slide."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(
                SampleRow.id, SampleRow.batch_id, SampleRow.duration_ms, SampleRow.metadata_json
            )
            .where(SampleRow.duration_ms.is_not(None))
            .where(SampleRow.target_profile == profile)
            .order_by(SampleRow.ended_at.asc())
        )
        out: list[TimedSample] = []
        for sid, bid, dur, meta_json in r.all():
            serial = None
            if meta_json:
                try:
                    serial = json.loads(meta_json).get("device_serial")
                except (ValueError, AttributeError):
                    serial = None
            out.append(
                TimedSample(
                    sample_id=sid, batch_id=bid, duration_ms=int(dur), device_serial=serial
                )
            )
        return out
```

- [ ] **Step 5: Run to verify pass**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py tests/unit/test_profile_health_queries.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/anomalies/store.py src/autoagent/storage/samples.py tests/unit/test_anomaly_store.py tests/unit/test_profile_health_queries.py; echo "EXIT=$?"
git add src/autoagent/anomalies/store.py src/autoagent/storage/samples.py tests/unit/test_anomaly_store.py tests/unit/test_profile_health_queries.py
git commit -m "feat(anomalies): add backfill support queries (dedup ids + timed samples)"
```

---

## Task 4: Backfill logic

**Files:** Create `src/autoagent/anomalies/backfill.py`; Test `tests/unit/test_anomaly_backfill.py`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_anomaly_backfill.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from autoagent.anomalies import store
from autoagent.anomalies.backfill import backfill_duration_anomalies
from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import upsert_sample


def _s(sid, profile, ms, ended):
    return SampleResult(
        id=sid, status="done", mode="api", target_profile=profile, duration_ms=ms, ended_at=ended
    )


@pytest.mark.asyncio
async def test_backfill_flags_outlier_and_is_idempotent():
    await init_db()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 25 tight-baseline samples, then a wild outlier — chronological
    for i in range(25):
        await upsert_sample("b", _s(f"h{i}", "p", 1000 + i, base + timedelta(minutes=i)))
    await upsert_sample("b", _s("out", "p", 50000, base + timedelta(hours=2)))

    result = await backfill_duration_anomalies()
    assert result.scanned == 26
    assert result.created == 1
    items, total = await store.list_anomalies(type="duration", limit=10, offset=0)
    assert total == 1 and items[0].sample_id == "out"
    assert items[0].detail["direction"] == "high"

    # idempotent — re-run creates nothing new
    again = await backfill_duration_anomalies()
    assert again.created == 0
    _, total2 = await store.list_anomalies(type="duration", limit=10, offset=0)
    assert total2 == 1


@pytest.mark.asyncio
async def test_backfill_respects_min_history():
    await init_db()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # only 5 samples incl. an outlier — under MIN_HISTORY, so nothing flags
    for i in range(4):
        await upsert_sample("b", _s(f"h{i}", "p", 1000, base + timedelta(minutes=i)))
    await upsert_sample("b", _s("out", "p", 99999, base + timedelta(minutes=10)))
    result = await backfill_duration_anomalies()
    assert result.created == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_backfill.py`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — create `src/autoagent/anomalies/backfill.py` (uses `distinct_sample_profiles()` from Task 3, NOT on-disk profile names — mirrors the live detector, which runs per-sample regardless of whether the profile YAML still exists):

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from autoagent.anomalies import store
from autoagent.anomalies.duration_detector import _format_summary, evaluate_duration
from autoagent.storage.samples import distinct_sample_profiles, timed_samples_for_profile

_log = logging.getLogger(__name__)

# Match the live detector's recency cap (see duration_detector.check_duration_anomaly,
# which baselines off recent_durations_for_profile(limit=500)).
_BASELINE_CAP = 500


@dataclass
class BackfillResult:
    scanned: int
    created: int


async def backfill_duration_anomalies() -> BackfillResult:
    """Scan every profile's historical timed samples through the same IQR
    duration detector the live hook uses, recording anomalies it finds.
    Point-in-time: each sample is judged against the samples before it.
    Idempotent: samples that already have a duration anomaly are skipped."""
    already = await store.existing_duration_sample_ids()
    scanned = 0
    created = 0
    for profile in await distinct_sample_profiles():
        samples = await timed_samples_for_profile(profile)
        durations: list[int] = []
        for ts in samples:
            scanned += 1
            baseline = durations[-_BASELINE_CAP:]
            verdict = evaluate_duration(ts.duration_ms, baseline)
            durations.append(ts.duration_ms)
            if verdict is None or ts.sample_id in already:
                continue
            await store.record_anomaly(
                type="duration",
                batch_id=ts.batch_id,
                sample_id=ts.sample_id,
                target_profile=profile,
                device_serial=ts.device_serial,
                summary=_format_summary(verdict),
                detail=verdict,
            )
            already.add(ts.sample_id)
            created += 1
    _log.info("duration backfill: scanned=%d created=%d", scanned, created)
    return BackfillResult(scanned=scanned, created=created)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_backfill.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/anomalies/backfill.py tests/unit/test_anomaly_backfill.py; echo "EXIT=$?"
git add src/autoagent/anomalies/backfill.py tests/unit/test_anomaly_backfill.py
git commit -m "feat(anomalies): add idempotent point-in-time duration backfill"
```

---

## Task 5: Backfill endpoint

**Files:** Modify `src/autoagent/api/anomalies.py`; Test `tests/integration/test_anomalies_endpoints.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/integration/test_anomalies_endpoints.py`:

```python
@pytest.mark.asyncio
async def test_backfill_endpoint(client):
    from datetime import datetime, timedelta, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(25):
        await upsert_sample(
            "b",
            SampleResult(id=f"h{i}", status="done", mode="api", target_profile="p",
                         duration_ms=1000 + i, ended_at=base + timedelta(minutes=i)),
        )
    await upsert_sample(
        "b",
        SampleResult(id="out", status="done", mode="api", target_profile="p",
                     duration_ms=50000, ended_at=base + timedelta(hours=2)),
    )
    r = await client.post("/api/v1/anomalies/backfill", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["scanned"] == 26 and body["created"] == 1
```

(No profile YAML needed — backfill derives its profile set from the samples table via `distinct_sample_profiles()`, so seeding samples for profile `p` is sufficient.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_anomalies_endpoints.py -k backfill`
Expected: FAIL — 404.

- [ ] **Step 3: Implement the endpoint** — in `src/autoagent/api/anomalies.py`, add the import and route (place it before `POST /{anomaly_id}/acknowledge`; a static `backfill` path won't collide with the int `anomaly_id`, but keeping it above is clean):

```python
from autoagent.anomalies.backfill import backfill_duration_anomalies


@router.post("/backfill")
async def backfill_anomalies() -> dict[str, int]:
    result = await backfill_duration_anomalies()
    return {"scanned": result.scanned, "created": result.created}
```

- [ ] **Step 4: Run to verify it passes** (add the `save_profile_yaml("p", ...)` line to the test if the count is 0)

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_anomalies_endpoints.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/api/anomalies.py tests/integration/test_anomalies_endpoints.py; echo "EXIT=$?"
git add src/autoagent/api/anomalies.py tests/integration/test_anomalies_endpoints.py
git commit -m "feat(anomalies): add POST /anomalies/backfill endpoint"
```

---

## Task 6: Backfill button (Config page)

**Files:** Modify `web/src/api/anomalies.ts`, `web/src/pages/Config.tsx`; Test `web/src/pages/Config.test.tsx` (if present) or a focused new test.

- [ ] **Step 1: Add the api hook** — in `web/src/api/anomalies.ts`:

```ts
export function useBackfillAnomalies() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      (await client.post<{ scanned: number; created: number }>('/anomalies/backfill')).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['anomalies'] })
    },
  })
}
```

- [ ] **Step 2: Add the button** — in `web/src/pages/Config.tsx`, in the DingTalk notifications section (near the other notification fields), add a button modeled on the existing `立即备份` button. Use `App.useApp()`'s `message` (already in the file) to report the result:

```tsx
// near the top of the component, with the other hooks:
const backfill = useBackfillAnomalies()
// ...in the notifications section JSX:
<Button
  loading={backfill.isPending}
  onClick={async () => {
    try {
      const r = await backfill.mutateAsync()
      message.success(`扫描 ${r.scanned} 条，新增 ${r.created} 条异常`)
    } catch (e) {
      message.error((e as Error).message)
    }
  }}
>
  扫描历史生成异常
</Button>
```

Import `useBackfillAnomalies` from `../api/anomalies`. Read the file first to place the button inside the DingTalk `RuleSection` consistently and to confirm `message` is in scope (it is via `App.useApp()`).

- [ ] **Step 3: Typecheck + lint + a smoke test** — if `Config.test.tsx` exists, add a test mocking `useBackfillAnomalies` to return `{ scanned: 5, created: 2 }` and asserting the button click shows the success message; otherwise rely on tsc/lint + the existing Config tests:

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run src/pages/Config.test.tsx`
Expected: clean + pass (Config tests unaffected).

- [ ] **Step 4: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/api/anomalies.ts src/pages/Config.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/api/anomalies.ts web/src/pages/Config.tsx
git commit -m "feat(web): add a 'scan history for anomalies' button to Config"
```

---

## Task 7: Digest config field + `anomalies_created_since`

**Files:** Modify `src/autoagent/models/api.py`, `src/autoagent/anomalies/store.py`; Test `tests/unit/test_anomaly_store.py`.

- [ ] **Step 1: Add the config field** — in `src/autoagent/models/api.py`, add to `DingTalkNotificationConfig` (near the other fields, e.g. after `anr_check_enabled`):

```python
    # Periodic anomaly digest: every N hours, DingTalk a summary of anomalies
    # created since the last digest. 0 = off. Reuses enabled/webhook_url/secret.
    digest_interval_hours: int = 0
```

- [ ] **Step 2: Write the failing store test** — append to `tests/unit/test_anomaly_store.py`:

```python
@pytest.mark.asyncio
async def test_anomalies_created_since():
    from datetime import datetime, timedelta, timezone

    await init_db()
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    now = datetime.now(timezone.utc)
    assert len(await store.anomalies_created_since(now - timedelta(hours=1))) == 1
    assert len(await store.anomalies_created_since(now + timedelta(hours=1))) == 0
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py -k created_since`
Expected: FAIL — undefined.

- [ ] **Step 4: Implement** — add to `src/autoagent/anomalies/store.py`:

```python
async def anomalies_created_since(since: datetime) -> list[AnomalyRecord]:
    """All anomalies created at/after `since`, newest first — feeds the
    periodic digest."""
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(AnomalyRow)
            .where(AnomalyRow.created_at >= since)
            .order_by(AnomalyRow.created_at.desc())
        )
        return [_row_to_record(row) for row in r.scalars().all()]
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_store.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/models/api.py src/autoagent/anomalies/store.py tests/unit/test_anomaly_store.py; echo "EXIT=$?"
git add src/autoagent/models/api.py src/autoagent/anomalies/store.py tests/unit/test_anomaly_store.py
git commit -m "feat(anomalies): add digest_interval_hours config + anomalies_created_since"
```

---

## Task 8: Digest markdown builder (pure)

**Files:** Create `src/autoagent/anomalies/digest.py`; Test `tests/unit/test_anomaly_digest.py`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_anomaly_digest.py`:

```python
from datetime import datetime, timezone

from autoagent.anomalies.digest import build_digest_markdown
from autoagent.models.api import AnomalyRecord


def _a(type_, profile, sid):
    return AnomalyRecord(
        id=1, type=type_, batch_id="b", sample_id=sid, target_profile=profile,
        device_serial=None, summary=f"{type_} on {profile}", detail={},
        acknowledged=False, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_build_digest_markdown_groups_and_totals():
    anomalies = [
        _a("duration", "doubao", "s1"),
        _a("duration", "doubao", "s2"),
        _a("anr", "kimi", "s3"),
    ]
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    md = build_digest_markdown(anomalies, since, app_base_url="")
    assert "共 3 条" in md
    assert "duration" in md and "anr" in md
    assert "doubao" in md  # top profile
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_digest.py`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — create `src/autoagent/anomalies/digest.py`:

```python
from __future__ import annotations

from collections import Counter
from datetime import datetime

from autoagent.models.api import AnomalyRecord

_TOP_EXAMPLES = 3


def _ref(app_base_url: str, batch_id: str, sample_id: str) -> str:
    base = app_base_url.rstrip("/")
    if base:
        return f"[{sample_id}]({base}/batches/{batch_id}/samples/{sample_id})"
    return f"`{batch_id}/{sample_id}`"


def build_digest_markdown(
    anomalies: list[AnomalyRecord], since: datetime, app_base_url: str
) -> str:
    """DingTalk markdown summarizing anomalies created since `since`: total,
    counts by type and by profile, and a few example rows. Pure — no I/O."""
    total = len(anomalies)
    by_type = Counter(a.type for a in anomalies)
    by_profile = Counter(a.target_profile for a in anomalies)
    type_line = " / ".join(f"{t} {n}" for t, n in by_type.most_common())
    profile_line = " / ".join(f"{p}({n})" for p, n in by_profile.most_common(5))
    lines = [
        "### 📊 异常摘要",
        f"- **自** {since.strftime('%Y-%m-%d %H:%M')} **以来共 {total} 条新异常**",
        f"- **按类型**: {type_line}",
        f"- **Top Profile**: {profile_line}",
        "- **举例**:",
    ]
    for a in anomalies[:_TOP_EXAMPLES]:
        lines.append(f"  - {a.summary} {_ref(app_base_url, a.batch_id, a.sample_id)}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_anomaly_digest.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/anomalies/digest.py tests/unit/test_anomaly_digest.py; echo "EXIT=$?"
git add src/autoagent/anomalies/digest.py tests/unit/test_anomaly_digest.py
git commit -m "feat(anomalies): add the digest markdown builder"
```

---

## Task 9: Digest loop + lifespan wiring

**Files:** Modify `src/autoagent/maintenance/scheduler.py`, `src/autoagent/main.py`; Test `tests/unit/test_digest_loop.py`.

- [ ] **Step 1: Write the failing test** — create `tests/unit/test_digest_loop.py`. It tests the tick function directly (not the infinite loop), mocking `send_markdown`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from autoagent.anomalies import store
from autoagent.maintenance import scheduler
from autoagent.storage.configs import get_config, put_config
from autoagent.storage.database import init_db


@pytest.mark.asyncio
async def test_digest_tick_sends_and_advances(monkeypatch):
    await init_db()
    sent = []

    async def fake_send(**kw):
        sent.append(kw)

        class _R:
            ok = True

        return _R()

    monkeypatch.setattr(scheduler, "send_markdown", fake_send)
    await put_config(
        "notifications",
        {"enabled": True, "webhook_url": "http://x", "digest_interval_hours": 24},
    )
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    await scheduler._digest_tick_once()
    assert len(sent) == 1  # sent because there were new anomalies
    state = await get_config("anomaly_digest_state")
    assert state and state.get("last_sent")  # advanced


@pytest.mark.asyncio
async def test_digest_tick_skips_send_when_no_new(monkeypatch):
    await init_db()
    sent = []

    async def fake_send(**kw):
        sent.append(kw)

        class _R:
            ok = True

        return _R()

    monkeypatch.setattr(scheduler, "send_markdown", fake_send)
    await put_config(
        "notifications",
        {"enabled": True, "webhook_url": "http://x", "digest_interval_hours": 24},
    )
    # set last_sent to now so no anomalies are "new"
    await put_config(
        "anomaly_digest_state",
        {"last_sent": datetime.now(timezone.utc).isoformat()},
    )
    await scheduler._digest_tick_once()
    assert sent == []  # nothing to send


@pytest.mark.asyncio
async def test_digest_tick_disabled(monkeypatch):
    await init_db()
    sent = []

    async def fake_send(**kw):
        sent.append(kw)
        return type("R", (), {"ok": True})()

    monkeypatch.setattr(scheduler, "send_markdown", fake_send)
    await put_config("notifications", {"enabled": False, "digest_interval_hours": 24})
    await store.record_anomaly(
        type="duration", batch_id="b", sample_id="s1", target_profile="p",
        device_serial=None, summary="x", detail={},
    )
    await scheduler._digest_tick_once()
    assert sent == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_digest_loop.py`
Expected: FAIL — `_digest_tick_once`/`send_markdown` attr not on scheduler.

- [ ] **Step 3: Implement the tick + loop** — in `src/autoagent/maintenance/scheduler.py`, add the imports at the top (with the existing ones):

```python
from datetime import datetime, timezone

from autoagent.anomalies import store as anomaly_store
from autoagent.anomalies.digest import build_digest_markdown
from autoagent.notifications.dingtalk import send_markdown
from autoagent.storage.configs import put_config
```

(`get_config` is already imported.) Add constants near the other delay consts:

```python
_DIGEST_STARTUP_DELAY_SEC = 300.0
_DIGEST_STATE_KEY = "anomaly_digest_state"
```

Then add the tick + loop:

```python
async def _digest_tick_once() -> None:
    cfg = await get_config("notifications") or {}
    if not (cfg.get("enabled") and cfg.get("webhook_url")):
        return
    interval = int(cfg.get("digest_interval_hours") or 0)
    if interval <= 0:
        return

    now = datetime.now(timezone.utc)
    state = await get_config(_DIGEST_STATE_KEY) or {}
    last_raw = state.get("last_sent")
    if last_raw:
        try:
            last = datetime.fromisoformat(last_raw)
        except ValueError:
            last = now - timedelta(hours=interval)
    else:
        last = now - timedelta(hours=interval)

    # Not yet due — the loop ticks more often than the interval to stay responsive
    # to config changes, so gate on elapsed time here.
    if last_raw and (now - last) < timedelta(hours=interval):
        return

    anomalies = await anomaly_store.anomalies_created_since(last)
    if not anomalies:
        # nothing to report, but advance so the window doesn't grow unbounded
        await put_config(_DIGEST_STATE_KEY, {"last_sent": now.isoformat()})
        return

    text = build_digest_markdown(anomalies, last, str(cfg.get("app_base_url") or ""))
    sr = await send_markdown(
        webhook_url=str(cfg["webhook_url"]).strip(),
        secret=(str(cfg.get("secret")).strip() or None) if cfg.get("secret") else None,
        title="[AutoAgent] 异常摘要",
        text=text,
        at_mobiles=list(cfg.get("at_mobiles") or []),
        at_all=bool(cfg.get("at_all")),
    )
    if sr.ok:
        await put_config(_DIGEST_STATE_KEY, {"last_sent": now.isoformat()})
    else:
        _log.warning("anomaly digest send failed; will retry next tick")


async def run_digest_loop() -> None:
    """Periodic anomaly digest. Ticks hourly; each tick sends only if enabled
    and digest_interval_hours has elapsed since the last send."""
    try:
        await asyncio.sleep(_DIGEST_STARTUP_DELAY_SEC)
    except asyncio.CancelledError:
        return
    while True:
        try:
            await _digest_tick_once()
        except Exception:  # noqa: BLE001
            _log.exception("digest tick failed")
        try:
            await asyncio.sleep(3600.0)
        except asyncio.CancelledError:
            return
```

Add `from datetime import timedelta` to the datetime import (`from datetime import datetime, timedelta, timezone`).

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_digest_loop.py`
Expected: PASS (3 tests). (The first test has no `last_sent` state, so the `if last_raw and ...` due-gate is skipped and it sends immediately — verify this matches; if the first test needs `last_raw` unset to send, that's the intended path.)

- [ ] **Step 5: Wire into lifespan** — in `src/autoagent/main.py`:
  - Change the import: `from autoagent.maintenance.scheduler import run_backup_loop, run_digest_loop, run_retention_loop`.
  - Add the task and include it in `background_tasks`:
    ```python
    backup_task = asyncio.create_task(run_backup_loop())
    digest_task = asyncio.create_task(run_digest_loop())
    update_task = asyncio.create_task(run_update_fetch_loop())
    background_tasks = (monitor_task, retention_task, backup_task, digest_task, update_task)
    ```

- [ ] **Step 6: Run the scheduler/main tests + confirm import**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_digest_loop.py && uv run python -c "import autoagent.main"`
Expected: PASS + no import error.

- [ ] **Step 7: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/maintenance/scheduler.py src/autoagent/main.py tests/unit/test_digest_loop.py; echo "EXIT=$?"
git add src/autoagent/maintenance/scheduler.py src/autoagent/main.py tests/unit/test_digest_loop.py
git commit -m "feat(anomalies): add the periodic DingTalk digest loop"
```

---

## Task 10: Digest config field (frontend)

**Files:** Modify `web/src/pages/Config.tsx`; Modify the TS notification config type if one exists (`web/src/types/api.ts` or `web/src/api/config.ts`).

- [ ] **Step 1: Add the field to the notify form** — in `web/src/pages/Config.tsx`, in the DingTalk notification `RuleSection`, add a `Form.Item` for `digest_interval_hours` mirroring the existing numeric fields:

```tsx
<Form.Item
  name="digest_interval_hours"
  label="异常摘要间隔 (小时)"
  extra="0 = 关闭。> 0：每隔该小时数，把自上次以来新增的异常汇总推送到上面的 DingTalk webhook。"
>
  <InputNumber min={0} max={168} />
</Form.Item>
```

Read `Config.tsx` first to place it in the DingTalk section consistently and confirm `Form.Item`/`InputNumber` import styles.

- [ ] **Step 2: Add the field to the TS type** — if there's a `DingTalkNotificationConfig` / notifications type in TS (grep `web/src/types/api.ts` and `web/src/api/config.ts`), add `digest_interval_hours?: number`. If the notify form is loosely typed (`Record<string, unknown>` / `any`), no type change is needed.

- [ ] **Step 3: Typecheck + lint + Config tests**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run src/pages/Config.test.tsx`
Expected: clean + pass.

- [ ] **Step 4: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/Config.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Config.tsx web/src/types/api.ts web/src/api/config.ts
git commit -m "feat(web): add the digest interval field to Config"
```

(Only `git add` the files you actually changed.)

---

## Task 11: Full verification + docs

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1: Backend fast suite + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run ruff check . && uv run pytest -q -m "not playwright and not android and not slow"`
Expected: lint clean, all tests pass.

- [ ] **Step 2: Frontend full suite + typecheck + lint + build**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run && pnpm build`
Expected: all green.

- [ ] **Step 3: CLAUDE.md changelog entry** — add a bullet documenting the three enhancements (time-range filter, idempotent point-in-time backfill via Config button, opt-in periodic DingTalk digest with `digest_interval_hours`), referencing the spec + this plan.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the anomaly center enhancements"
```

- [ ] **Step 5: Push + verify CI** — user pre-authorized. Push and confirm CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`.

---

## Self-Review

**1. Spec coverage:**
- Time filter (store + endpoint + RangePicker) → Tasks 1, 2. ✓
- Backfill support queries → Task 3. ✓
- Backfill logic (point-in-time, dedup, idempotent, MIN_HISTORY) → Task 4. ✓
- Backfill endpoint + button → Tasks 5, 6. ✓
- Digest config field + `anomalies_created_since` → Task 7. ✓
- Digest markdown builder → Task 8. ✓
- Digest loop (enabled gate, since-last, skip-when-empty-but-advance, no-advance-on-send-fail) + lifespan → Task 9. ✓
- Digest config field frontend → Task 10. ✓
- Testing throughout + verification → each task + Task 11. ✓

**2. Placeholder scan:** No TBD/TODO. Task 2/6/10 "read the file first to place consistently" notes name the exact file and pattern to match. Backfill's profile-set decision is resolved: sample-derived via `distinct_sample_profiles()` (Task 3), so no test needs an on-disk profile YAML.

**3. Type consistency:** `list_anomalies` keyword args (`created_after`/`created_before`) match between Task 1 store + endpoint. `TimedSample` fields (`sample_id/batch_id/duration_ms/device_serial`) match between Task 3 def and Task 4 usage. `distinct_sample_profiles()` defined Task 3, used Task 4. `BackfillResult(scanned, created)` consistent Task 4 → Task 5. `evaluate_duration`/`_format_summary` reused from `duration_detector` (existing). `build_digest_markdown(anomalies, since, app_base_url)` signature matches Task 8 def + Task 9 call. `anomalies_created_since(since)` matches Task 7 def + Task 9 call. `digest_interval_hours` consistent across models (Task 7), loop (Task 9), frontend (Task 10). `_digest_tick_once`/`send_markdown` on the `scheduler` module match Task 9 impl + the test's monkeypatch target.
