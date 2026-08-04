# Health Trends — Design

## Problem

The Profile Health dashboard (shipped 2026-08-04) is a *current* 7-day snapshot — one status per profile. It answers "is this profile healthy now?" but not "is it getting better or worse?". A profile trending downward (success rate slipping day over day, duration creeping up) looks identical to a stably-healthy one until it crosses a threshold.

## Goals

- Show each profile's trend over time for three metrics: success rate, average duration, sample volume.
- At-a-glance on the health card: an inline success-rate sparkline.
- On demand: clicking a card opens a modal with all three metrics as larger line charts.
- Data comes from the existing `samples` table, bucketed by day; no new persistence.

## Non-goals (this iteration)

- Configurable per-metric windows or granularities beyond a `days` query param (fixed daily buckets).
- Anomaly-overlay / annotations on the trend charts.
- Zero-filling days with no runs (gaps are simply not plotted).
- Trends for anything other than the per-profile health metrics.

## Charting approach

New frontend dependency: **`recharts`** (chosen over a hand-rolled SVG approach for its built-in axes/tooltips/responsiveness). To keep it out of the main bundle, the two recharts-using components (`ProfileSparkline`, `ProfileTrendModal`) are **lazy-loaded** (`React.lazy` + `Suspense`), matching how Monaco/`YamlEditor`/`LogViewer` are already split — recharts becomes its own chunk loaded only when the Health page renders.

## Backend

**New query** `storage/samples.py::daily_stats_by_profile(since: datetime) -> dict[str, list[DailyPoint]]`: one grouped SQL over `samples`, bucketing by `(target_profile, date(ended_at))`. Uses SQLite `func.strftime('%Y-%m-%d', SampleRow.ended_at)` for the day key. Per bucket aggregates:
- `done` = count of `status == "done"`,
- `total` = count of terminal-executed statuses (`done/failed/timeout/extraction_failed`) — the success-rate denominator,
- `avg_duration_ms` = `AVG(duration_ms)` over non-null durations,
- `sample_count` = `total`.

Filters `ended_at IS NOT NULL AND ended_at >= since AND status IN _TERMINAL_EXECUTED`. Returns, per profile, a list of `DailyPoint`s ordered by date ascending. Only days with terminal samples appear (no zero-fill).

**Schema** `DailyPoint` (`models/api.py`):
```python
class DailyPoint(BaseModel):
    date: str            # YYYY-MM-DD
    success_rate: float | None   # done/total; None when total==0 (shouldn't happen given the filter, but defensive)
    avg_duration_ms: float | None
    sample_count: int
```

**Endpoint** `GET /api/v1/profiles/trends?days=30` (on the existing profiles router, inherits `require_user`): `days` is `Query(30, ge=1, le=90)`. Computes `since = now - days` and returns `dict[str, list[DailyPoint]]` (profile → daily series). One request serves both the card sparklines and the modal (the modal just reads `trends[name]` from the already-fetched batch — no per-profile request).

## Frontend

- **Data layer** (`web/src/api/profileHealth.ts`): `useProfileTrends(days = 30)` → `GET /profiles/trends`. Types `DailyPoint` and `ProfileTrends = Record<string, DailyPoint[]>` in `web/src/types/api.ts`.
- **`web/src/components/ProfileSparkline.tsx`** (lazy, recharts): a minimal `LineChart` of the success-rate series — hidden axes/grid, no tooltip, fixed small size. Rendered inline on each health card next to 成功率. Empty/absent series → renders nothing (card still clickable).
- **`web/src/components/ProfileTrendModal.tsx`** (lazy, recharts): an AntD `Modal` (open when a `profileName` is set) with three `LineChart`s inside `ResponsiveContainer` — 成功率 / 平均耗时 / 样本量 — each with `XAxis` (date), `YAxis`, `Tooltip`. Reads its series from the passed-in `trends[profileName]`. No series → a "暂无趋势数据" empty state.
- **`Health.tsx` wiring**: calls `useProfileTrends()` alongside `useProfileHealth()`. Each `HealthCard` becomes clickable (opens the trend modal for that profile) and renders a `<Suspense><ProfileSparkline series={trends[name]} /></Suspense>` inline. A single `ProfileTrendModal` at the page level, driven by a `selectedProfile` state. The existing card click-throughs (name→edit, anomaly→center, device→screens) keep working — the card-body click opens the trend modal, while those specific links `stopPropagation` so they don't also open it.

## Error handling

- Trends failing to load doesn't break the health cards — sparklines just don't render (the health snapshot is independent of trends; `useProfileTrends` error is non-fatal to the page).
- A profile with no historical samples → empty series → no sparkline, modal shows "暂无趋势数据".
- `days` out of range → 422 (FastAPI query validation).

## Testing

**Backend:**
- `daily_stats_by_profile(since)`: multi-profile, multi-day samples → correct per-(profile, day) buckets (done/total/avg_duration/count); out-of-window samples excluded; days with no terminal samples absent; a day's success_rate = done/total.
- `GET /profiles/trends`: auth, response shape (profile → day series), `days` cap (422 at days>90), window boundary.

recharts' `ResponsiveContainer` measures 0×0 in jsdom and renders no chart, so the frontend tests `vi.mock('recharts')` with lightweight stub components (e.g. `LineChart` renders its children, `Line`/`XAxis`/etc. render a marker) and assert on the data/props the components pass in, not on rendered SVG.

**Frontend:**
- `useProfileTrends` hook test.
- `ProfileSparkline` (recharts mocked): given a non-empty series, passes it to the chart; an empty/undefined series renders nothing (no crash).
- `ProfileTrendModal` (recharts mocked): open with a series renders the three metric sections; `profileName=null` → modal not open; empty series → "暂无趋势数据".
- `Health.tsx`: clicking a card body opens the trend modal for the right profile; the name/anomaly/device links still do their own navigation and don't also open the modal (stopPropagation). Mock `ProfileSparkline`/`ProfileTrendModal` to lightweight stubs so the page test doesn't pull in recharts.
