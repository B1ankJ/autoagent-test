# Health Trends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-profile time-series trends (success rate / avg duration / sample volume) to the health dashboard — an inline success-rate sparkline on each card plus a click-to-open modal with all three metrics as recharts line charts.

**Architecture:** A new daily-bucketed samples query + a batch `GET /profiles/trends` endpoint. Frontend adds `recharts` (lazy-loaded, kept out of the main bundle) via a `ProfileSparkline` (cards) and `ProfileTrendModal` (detail), wired into the existing `Health.tsx`.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (SQLite), `uv`; React 18 + TS + AntD 5 + recharts, TanStack Query, Vitest.

---

## Context an implementer needs

- **`storage/samples.py`** imports `from sqlalchemy import func, select` and `SampleRow` (= `Sample`). It has `_TERMINAL_EXECUTED = ("done", "failed", "timeout", "extraction_failed")`, `success_stats_by_profile(since)`, `avg_duration_by_profile(since=None)`, `distinct_sample_profiles()`, `timed_samples_for_profile`. `Sample.ended_at` is a `DateTime` (nullable) stored naive-UTC-style; SQLite `strftime('%Y-%m-%d', ended_at)` buckets it by day.
- **Profiles router** (`api/profiles.py`): `router = APIRouter(prefix="/profiles", ... dependencies=[Depends(require_user)])`. Has `GET /profiles/health` (before `GET /{name}`). Add `GET /profiles/trends` alongside it (also before `/{name}`).
- **Health page** (`web/src/pages/Profiles/Health.tsx`): `HealthCard({ row, onOpenDevices })` renders the card; `Health()` calls `useProfileHealth()`, maps rows to `<HealthCard>` in a `Row`/`Col` grid, and holds a `deviceModal` state + `ProfileDeviceScreensModal`. Card has `<a>` links (name→`/profiles/<name>`, anomaly→`/system/anomalies?...`, device→opens device modal).
- **Data layer** (`web/src/api/profileHealth.ts`): `useProfileHealth()`, `summarizeHealth()`. Types `ProfileHealth`/`HealthStatus` in `web/src/types/api.ts`.
- **Lazy-loading pattern**: `YamlEditor`/`LogViewer` are `React.lazy` + `Suspense` to keep Monaco out of the main bundle — mirror it for recharts.
- **Tests**: backend `pytest-asyncio` auto mode, `await init_db()` first; integration copies `client`/`_login` from `tests/integration/test_anomalies_endpoints.py`. Run `uv run pytest -q <path>`; lint `uv run ruff check <files>; echo EXIT=$?`. Frontend `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run <path>`, `pnpm exec tsc --noEmit`, `pnpm lint`. recharts renders nothing in jsdom (`ResponsiveContainer` is 0×0) → frontend tests `vi.mock('recharts')`. pnpm cwd resets → prefix `cd .../web &&`.

---

## File Structure

- Modify `src/autoagent/storage/samples.py` (add `DailyBucket` + `daily_stats_by_profile`)
- Modify `src/autoagent/models/api.py` (add `DailyPoint`)
- Modify `src/autoagent/api/profiles.py` (add `GET /trends`)
- Modify `web/src/types/api.ts` (`DailyPoint`, `ProfileTrends`), `web/src/api/profileHealth.ts` (`useProfileTrends`)
- Create `web/src/components/ProfileSparkline.tsx`, `web/src/components/ProfileTrendModal.tsx` (+ `.test.tsx` each)
- Modify `web/src/pages/Profiles/Health.tsx` (+ `Health.test.tsx`)
- Modify `web/package.json` (recharts)
- Tests: `tests/unit/test_profile_health_queries.py` (extend), `tests/integration/test_profile_health_endpoint.py` (extend); frontend component + page tests, `web/src/api/profileHealth.test.ts` (if present, extend)

---

## Task 1: Daily-bucket query + `DailyPoint` schema

**Files:** Modify `src/autoagent/storage/samples.py`, `src/autoagent/models/api.py`; Test `tests/unit/test_profile_health_queries.py`.

- [ ] **Step 1: Add the schema** to `src/autoagent/models/api.py` (append at end):

```python
class DailyPoint(BaseModel):
    date: str  # YYYY-MM-DD
    success_rate: float | None = None
    avg_duration_ms: float | None = None
    sample_count: int = 0
```

- [ ] **Step 2: Write the failing test** — append to `tests/unit/test_profile_health_queries.py`:

```python
@pytest.mark.asyncio
async def test_daily_stats_by_profile_buckets_by_day():
    from autoagent.storage.samples import daily_stats_by_profile

    await init_db()
    d1 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # day 1: 2 done + 1 failed (durations 100/200 on the done ones)
    await upsert_sample("b", SampleResult(id="a1", status="done", mode="api",
                                          target_profile="p", duration_ms=100, ended_at=d1))
    await upsert_sample("b", SampleResult(id="a2", status="done", mode="api",
                                          target_profile="p", duration_ms=200, ended_at=d1))
    await upsert_sample("b", SampleResult(id="a3", status="failed", mode="api",
                                          target_profile="p", duration_ms=None, ended_at=d1))
    # day 2: 1 done
    await upsert_sample("b", SampleResult(id="a4", status="done", mode="api",
                                          target_profile="p", duration_ms=400, ended_at=d2))
    # out of window
    await upsert_sample("b", SampleResult(id="a5", status="done", mode="api",
                                          target_profile="p", duration_ms=999, ended_at=old))

    since = datetime(2026, 2, 15, tzinfo=timezone.utc)
    trends = await daily_stats_by_profile(since)
    pts = trends["p"]
    assert [p.date for p in pts] == ["2026-03-01", "2026-03-02"]  # ascending, old excluded
    assert pts[0].sample_count == 3 and round(pts[0].success_rate, 3) == round(2 / 3, 3)
    assert round(pts[0].avg_duration_ms) == 150  # (100+200)/2, null failure excluded from AVG
    assert pts[1].sample_count == 1 and pts[1].success_rate == 1.0
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_profile_health_queries.py -k daily_stats`
Expected: FAIL — `daily_stats_by_profile` undefined.

- [ ] **Step 4: Implement** — in `src/autoagent/storage/samples.py`, add `case` to the sqlalchemy import (`from sqlalchemy import case, func, select`), a `DailyBucket` isn't needed (return the schema directly), and the function. Import the schema at top: `from autoagent.models.api import DailyPoint, SampleResult` (it already imports `SampleResult` — extend that line). Then:

```python
async def daily_stats_by_profile(since: datetime) -> dict[str, list[DailyPoint]]:
    """Per profile, a daily time series (ascending) of success rate / avg
    duration / sample count over terminal-executed samples with ended_at >=
    since. Buckets by date(ended_at); only days with samples appear."""
    day = func.strftime("%Y-%m-%d", SampleRow.ended_at)
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(
            select(
                SampleRow.target_profile,
                day.label("day"),
                func.count().label("total"),
                func.sum(case((SampleRow.status == "done", 1), else_=0)).label("done"),
                func.avg(SampleRow.duration_ms).label("avg_ms"),
            )
            .where(SampleRow.status.in_(_TERMINAL_EXECUTED))
            .where(SampleRow.ended_at.is_not(None))
            .where(SampleRow.ended_at >= since)
            .group_by(SampleRow.target_profile, "day")
            .order_by(SampleRow.target_profile, "day")
        )
        out: dict[str, list[DailyPoint]] = {}
        for profile, d, total, done, avg_ms in r.all():
            out.setdefault(profile, []).append(
                DailyPoint(
                    date=d,
                    success_rate=(done / total) if total else None,
                    avg_duration_ms=float(avg_ms) if avg_ms is not None else None,
                    sample_count=int(total),
                )
            )
        return out
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_profile_health_queries.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/storage/samples.py src/autoagent/models/api.py tests/unit/test_profile_health_queries.py; echo "EXIT=$?"
git add src/autoagent/storage/samples.py src/autoagent/models/api.py tests/unit/test_profile_health_queries.py
git commit -m "feat(health): add daily per-profile stats query for trends"
```

---

## Task 2: `GET /profiles/trends` endpoint

**Files:** Modify `src/autoagent/api/profiles.py`; Test `tests/integration/test_profile_health_endpoint.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/integration/test_profile_health_endpoint.py`:

```python
@pytest.mark.asyncio
async def test_profile_trends_endpoint(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="s1", status="done", mode="api",
                                          target_profile="pt", duration_ms=100, ended_at=now))
    r = await client.get("/api/v1/profiles/trends?days=30", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "pt" in body
    assert body["pt"][0]["success_rate"] == 1.0 and body["pt"][0]["sample_count"] == 1


@pytest.mark.asyncio
async def test_profile_trends_days_cap(client):
    h = await _login(client)
    r = await client.get("/api/v1/profiles/trends?days=999", headers=h)
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_profile_health_endpoint.py -k trends`
Expected: FAIL — 404.

- [ ] **Step 3: Implement** — in `src/autoagent/api/profiles.py`: add imports (`from datetime import datetime, timedelta, timezone`, `from fastapi import Query` — check what's already imported; `from autoagent.models.api import DailyPoint`, `from autoagent.storage.samples import daily_stats_by_profile`). Add the route **before** `@router.get("/{name}")`:

```python
@router.get("/trends", response_model=dict[str, list[DailyPoint]])
async def profiles_trends(days: int = Query(30, ge=1, le=90)) -> dict[str, list[DailyPoint]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return await daily_stats_by_profile(since)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_profile_health_endpoint.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/api/profiles.py tests/integration/test_profile_health_endpoint.py; echo "EXIT=$?"
git add src/autoagent/api/profiles.py tests/integration/test_profile_health_endpoint.py
git commit -m "feat(health): add GET /profiles/trends endpoint"
```

---

## Task 3: Frontend data layer

**Files:** Modify `web/src/types/api.ts`, `web/src/api/profileHealth.ts`; Test `web/src/api/profileHealth.test.ts` (extend if present, else skip — hook is thin).

- [ ] **Step 1: Add types** to `web/src/types/api.ts`:

```ts
export interface DailyPoint {
  date: string
  success_rate: number | null
  avg_duration_ms: number | null
  sample_count: number
}

export type ProfileTrends = Record<string, DailyPoint[]>
```

- [ ] **Step 2: Add the hook** to `web/src/api/profileHealth.ts`:

```ts
import { ProfileTrends } from '../types/api'
// ...
export function useProfileTrends(days = 30) {
  return useQuery({
    queryKey: ['profiles', 'trends', days],
    queryFn: async () =>
      (await client.get<ProfileTrends>('/profiles/trends', { params: { days } })).data,
  })
}
```

(Add `ProfileTrends`/`DailyPoint` to the existing `import { ... } from '../types/api'` line rather than a second import.)

- [ ] **Step 3: Typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/types/api.ts web/src/api/profileHealth.ts
git commit -m "feat(web): add the profile-trends data layer"
```

---

## Task 4: recharts dependency + `ProfileSparkline`

**Files:** Modify `web/package.json` (pnpm add); Create `web/src/components/ProfileSparkline.tsx`, `web/src/components/ProfileSparkline.test.tsx`.

- [ ] **Step 1: Add recharts**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm add recharts`
Expected: `web/package.json` gains `recharts` under dependencies; lockfile updates.

- [ ] **Step 2: Write the failing test** — create `web/src/components/ProfileSparkline.test.tsx`. Mock recharts so jsdom doesn't need layout:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DailyPoint } from '../types/api'
import { ProfileSparkline } from './ProfileSparkline'

vi.mock('recharts', () => ({
  LineChart: ({ data, children }: { data: unknown[]; children: React.ReactNode }) => (
    <div data-testid="sparkline" data-points={(data as unknown[]).length}>
      {children}
    </div>
  ),
  Line: () => <div data-testid="line" />,
}))

function pt(date: string, rate: number): DailyPoint {
  return { date, success_rate: rate, avg_duration_ms: 100, sample_count: 5 }
}

describe('ProfileSparkline', () => {
  it('renders a line chart for a non-empty series', () => {
    render(<ProfileSparkline series={[pt('2026-03-01', 1), pt('2026-03-02', 0.8)]} />)
    expect(screen.getByTestId('sparkline')).toHaveAttribute('data-points', '2')
    expect(screen.getByTestId('line')).toBeInTheDocument()
  })

  it('renders nothing for an empty series', () => {
    const { container } = render(<ProfileSparkline series={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/components/ProfileSparkline.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement** — create `web/src/components/ProfileSparkline.tsx` (default export so it can be `React.lazy`-loaded):

```tsx
import { Line, LineChart } from 'recharts'
import type { DailyPoint } from '../types/api'

export function ProfileSparkline({ series }: { series: DailyPoint[] }) {
  if (!series || series.length === 0) return null
  const data = series.map((p) => ({
    date: p.date,
    value: p.success_rate === null ? null : Math.round(p.success_rate * 100),
  }))
  return (
    <LineChart width={72} height={22} data={data}>
      <Line
        type="monotone"
        dataKey="value"
        stroke="#389e0d"
        strokeWidth={1.5}
        dot={false}
        isAnimationActive={false}
        connectNulls
      />
    </LineChart>
  )
}

export default ProfileSparkline
```

- [ ] **Step 5: Run to verify it passes + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/components/ProfileSparkline.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean.

- [ ] **Step 6: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/components/ProfileSparkline.tsx src/components/ProfileSparkline.test.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/package.json web/pnpm-lock.yaml web/src/components/ProfileSparkline.tsx web/src/components/ProfileSparkline.test.tsx
git commit -m "feat(web): add recharts + the profile success-rate sparkline"
```

---

## Task 5: `ProfileTrendModal`

**Files:** Create `web/src/components/ProfileTrendModal.tsx`, `web/src/components/ProfileTrendModal.test.tsx`.

- [ ] **Step 1: Write the failing test** — create `web/src/components/ProfileTrendModal.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DailyPoint } from '../types/api'
import { ProfileTrendModal } from './ProfileTrendModal'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="chart">{children}</div>
  ),
  Line: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  Tooltip: () => <div />,
  CartesianGrid: () => <div />,
}))

function pt(date: string): DailyPoint {
  return { date, success_rate: 0.9, avg_duration_ms: 100, sample_count: 5 }
}

describe('ProfileTrendModal', () => {
  it('renders three charts when open with a series', () => {
    render(
      <ProfileTrendModal profileName="qwen" series={[pt('2026-03-01'), pt('2026-03-02')]} onClose={() => {}} />,
    )
    expect(screen.getByText(/qwen/)).toBeInTheDocument()
    expect(screen.getAllByTestId('chart')).toHaveLength(3)
  })

  it('is not open when profileName is null', () => {
    render(<ProfileTrendModal profileName={null} series={[]} onClose={() => {}} />)
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument()
  })

  it('shows an empty state for an empty series', () => {
    render(<ProfileTrendModal profileName="qwen" series={[]} onClose={() => {}} />)
    expect(screen.getByText('暂无趋势数据')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/components/ProfileTrendModal.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — create `web/src/components/ProfileTrendModal.tsx`:

```tsx
import { Empty, Modal, Typography } from 'antd'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DailyPoint } from '../types/api'

interface Props {
  profileName: string | null
  series: DailyPoint[]
  onClose: () => void
}

function Metric({
  title,
  data,
  color,
}: {
  title: string
  data: Array<{ date: string; value: number | null }>
  color: string
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Typography.Text strong>{title}</Typography.Text>
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ProfileTrendModal({ profileName, series, onClose }: Props) {
  return (
    <Modal
      open={!!profileName}
      title={`趋势 · ${profileName ?? ''}`}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnClose
    >
      {series.length === 0 ? (
        <Empty description="暂无趋势数据" />
      ) : (
        <>
          <Metric
            title="成功率 (%)"
            color="#389e0d"
            data={series.map((p) => ({
              date: p.date,
              value: p.success_rate === null ? null : Math.round(p.success_rate * 100),
            }))}
          />
          <Metric
            title="平均耗时 (ms)"
            color="#d48806"
            data={series.map((p) => ({ date: p.date, value: p.avg_duration_ms }))}
          />
          <Metric
            title="样本量"
            color="#2547d0"
            data={series.map((p) => ({ date: p.date, value: p.sample_count }))}
          />
        </>
      )}
    </Modal>
  )
}

export default ProfileTrendModal
```

- [ ] **Step 4: Run to verify it passes + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/components/ProfileTrendModal.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean.

- [ ] **Step 5: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/components/ProfileTrendModal.tsx src/components/ProfileTrendModal.test.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/components/ProfileTrendModal.tsx web/src/components/ProfileTrendModal.test.tsx
git commit -m "feat(web): add the profile trend modal (3 metric charts)"
```

---

## Task 6: Wire trends into the Health page

**Files:** Modify `web/src/pages/Profiles/Health.tsx`, `web/src/pages/Profiles/Health.test.tsx`.

- [ ] **Step 1: Write the failing test** — add to `web/src/pages/Profiles/Health.test.tsx`. First add mocks at the top (near the existing `vi.mock('../../api/profileHealth', ...)`): mock `useProfileTrends` and stub the two lazy chart components so the page test doesn't pull in recharts:

```tsx
// extend the existing profileHealth mock to also provide useProfileTrends:
//   in the vi.mock factory return, add: useProfileTrends: () => useProfileTrends(),
// and declare: const useProfileTrends = vi.fn()
vi.mock('../../components/ProfileSparkline', () => ({
  ProfileSparkline: () => <div data-testid="sparkline" />,
  default: () => <div data-testid="sparkline" />,
}))
vi.mock('../../components/ProfileTrendModal', () => ({
  ProfileTrendModal: ({ profileName }: { profileName: string | null }) =>
    profileName ? <div>trend-modal:{profileName}</div> : null,
  default: ({ profileName }: { profileName: string | null }) =>
    profileName ? <div>trend-modal:{profileName}</div> : null,
}))
```

Then a test:

```tsx
it('opens the trend modal when a card body is clicked', async () => {
  useProfileHealth.mockReturnValue({
    data: [row({ name: 'trendp', status: 'green' })],
    isLoading: false,
    isError: false,
  })
  useProfileTrends.mockReturnValue({ data: { trendp: [] } })

  renderWithProviders(
    <Routes>
      <Route path="/profiles/health" element={<Health />} />
    </Routes>,
    { initialPath: '/profiles/health' },
  )
  // click the card (the profile name is a stopPropagation link, so click the platform tag area / card body)
  await userEvent.click(await screen.findByText('api')) // the platform Tag inside the card body
  expect(await screen.findByText('trend-modal:trendp')).toBeInTheDocument()
})
```

Note: set `useProfileTrends.mockReturnValue({ data: {} })` (or per-test) in the existing `beforeEach`/`afterEach` if the other tests break for want of it — give it a default `{ data: {} }` return so cards render without trend data.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Profiles/Health.test.tsx`
Expected: FAIL (no trend modal / useProfileTrends not wired).

- [ ] **Step 3: Implement** — in `web/src/pages/Profiles/Health.tsx`:
  - Imports: `import { lazy, Suspense, useMemo, useState } from 'react'` (add `lazy`/`Suspense`); `import { summarizeHealth, useProfileHealth, useProfileTrends } from '../../api/profileHealth'`; `import type { DailyPoint } from '../../types/api'`. Lazy-load the chart components:
    ```tsx
    const ProfileSparkline = lazy(() => import('../../components/ProfileSparkline'))
    const ProfileTrendModal = lazy(() => import('../../components/ProfileTrendModal'))
    ```
  - `HealthCard` gains props `onOpenTrend: (name: string) => void` and `trendSeries: DailyPoint[]`. Make the `<Card>` clickable (`onClick={() => onOpenTrend(row.name)}`, `style={{ cursor: 'pointer' }}`). On the existing `<a>` links (name, anomaly) and the device `<a>`, wrap their `onClick` to `stopPropagation` first, e.g.:
    ```tsx
    <a onClick={(e) => { e.stopPropagation(); navigate(`/profiles/${row.name}`) }} ...>
    ```
    (device link: `onClick={(e) => { e.stopPropagation(); onOpenDevices(row) }}`). Render the sparkline inline next to 成功率:
    ```tsx
    成功率 {row.success_rate === null ? '—' : `${Math.round(row.success_rate * 100)}%`}{' '}
    <Suspense fallback={null}>
      <ProfileSparkline series={trendSeries} />
    </Suspense>
    ```
  - `Health()`: `const trends = useProfileTrends()`, `const [trendProfile, setTrendProfile] = useState<string | null>(null)`. Pass `onOpenTrend={setTrendProfile}` and `trendSeries={trends.data?.[r.name] ?? []}` to each `<HealthCard>`. At the page bottom (next to the device modal), render:
    ```tsx
    <Suspense fallback={null}>
      <ProfileTrendModal
        profileName={trendProfile}
        series={trendProfile ? (trends.data?.[trendProfile] ?? []) : []}
        onClose={() => setTrendProfile(null)}
      />
    </Suspense>
    ```

- [ ] **Step 4: Run to verify it passes + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Profiles/Health.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean. (If the existing Health tests fail because `useProfileTrends` returns undefined, give it a default `{ data: {} }` mock return in the test file's setup.)

- [ ] **Step 5: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/Profiles/Health.tsx src/pages/Profiles/Health.test.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Profiles/Health.tsx web/src/pages/Profiles/Health.test.tsx
git commit -m "feat(web): show trend sparkline on cards + trend modal on click"
```

---

## Task 7: Full verification + docs

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1: Backend fast suite + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run ruff check . && uv run pytest -q -m "not playwright and not android and not slow"`
Expected: lint clean, all pass.

- [ ] **Step 2: Frontend full suite + typecheck + lint + build**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run && pnpm build`
Expected: all green. **Confirm the build output shows a separate recharts chunk** (not merged into the main `index-*.js`) — the lazy-loading should split it out.

- [ ] **Step 3: CLAUDE.md changelog entry** — document the health trends (daily-bucket query, `/profiles/trends` endpoint, recharts as a lazy-loaded dependency, card sparkline + click-to-open 3-metric trend modal), referencing the spec + this plan.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the health trends feature"
```

- [ ] **Step 5: Push + verify CI** — user pre-authorized. Push and confirm CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`.

---

## Self-Review

**1. Spec coverage:**
- Daily-bucket query (success/duration/count, terminal filter, window, day buckets) → Task 1. ✓
- `DailyPoint` schema → Task 1. ✓
- `/profiles/trends?days=` batch endpoint (days cap) → Task 2. ✓
- Frontend types + `useProfileTrends` → Task 3. ✓
- recharts dep (lazy) → Tasks 4/5 (components) + Task 6 (`React.lazy`). ✓
- Card inline success-rate sparkline → Tasks 4 + 6. ✓
- Click-to-open 3-metric modal → Tasks 5 + 6. ✓
- Existing card links stopPropagation → Task 6. ✓
- Lazy-loading keeps recharts out of main bundle → Task 6 (`lazy(() => import(...))`) + Task 7 Step 2 (verify chunk split). ✓
- Testing (query, endpoint, hook, both components with recharts mocked, page click) → each task + Task 7. ✓

**2. Placeholder scan:** No TBD/TODO. Task 6's test note ("give useProfileTrends a default mock so existing tests don't break") is a concrete instruction, not vague.

**3. Type consistency:** `DailyPoint` fields (`date/success_rate/avg_duration_ms/sample_count`) identical between Task 1 (Pydantic), Task 3 (TS), and Tasks 4/5/6 (consumers). `daily_stats_by_profile(since) -> dict[str, list[DailyPoint]]` matches Task 1 def + Task 2 endpoint call. `ProfileTrends = Record<string, DailyPoint[]>` matches the endpoint's response shape. `ProfileSparkline({ series })` + `ProfileTrendModal({ profileName, series, onClose })` prop shapes match their defs (Tasks 4/5) and Health's usage (Task 6). `useProfileTrends()` returns `{ data: ProfileTrends }` consumed as `trends.data?.[name]` in Task 6.
