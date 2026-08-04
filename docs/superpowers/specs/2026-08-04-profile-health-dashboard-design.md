# Profile Health Dashboard — Design

## Problem

Per-profile health is scattered: avg duration shows on the Profiles list, anomalies live in the Anomaly Center, success/failure is buried in individual batches, and device-pool liveness is on the Devices page. There's no single "which of my profiles are unhealthy right now" view — you have to cross-reference four places.

## Goals

- A dedicated dashboard page showing every profile as a health card: a top status block (🟢/🟡/🔴/⚪) plus four metrics — success rate, average duration, unacknowledged anomaly count, and device-pool status.
- Health is **recent-focused** (last 7 days) so a profile that failed months ago but is fine now doesn't read red.
- Overall status is **worst-of** the participating signals — one critical signal can't be averaged away by good ones.
- Worst profiles sort first; clicking through reaches the relevant detail (anomaly count → Anomaly Center filtered to that profile).

## Non-goals (this iteration)

- Historical health trend charts / time series (just current snapshot over the 7-day window).
- Configurable thresholds or window length (fixed constants this cut).
- Per-profile alerting off the health status (the Anomaly Center + DingTalk rules already cover alerting).
- Response-length / cross-profile comparative scoring.

## Data & metrics

Window: `since = now − 7 days`. Device status is live (current), not windowed.

| Signal | Source | New query |
|---|---|---|
| Success rate | `samples` grouped by `target_profile` + `status`, `ended_at >= since`; `done / (done+failed+timeout+extraction_failed)` | `storage/samples.py::success_stats_by_profile(since)` → `{profile: {done, total}}` |
| Avg duration | `avg(duration_ms)` where `duration_ms IS NOT NULL AND ended_at >= since`, grouped by profile | extend `avg_duration_by_profile(since: datetime | None = None)` with an optional `ended_at >= since` filter (default None = all-time, preserving existing callers) |
| Unacked anomalies | `anomalies` where `created_at >= since AND acknowledged = false`, grouped by `target_profile` | `anomalies/store.py::unacked_counts_by_profile(since)` → `{profile: count}` |
| Device pool | profile `serials` ∩ `devices` table `online`/`enabled` (only `android`/`agent_android`) | reuse `storage/devices.py::list_devices()` |

Terminal-executed statuses (the success-rate denominator): `done`, `failed`, `timeout`, `extraction_failed` — matches `rules.py::_DEVICE_EXECUTED_STATUSES`. `Sample` has no `created_at`; a terminal sample always has `ended_at`, so the window filters on `ended_at`.

Assembly in a new module `src/autoagent/health/profile_health.py::list_profile_health()`: pulls the four sources, and per profile builds a `ProfileHealth`.

## Health computation

Pure function `compute_health(metrics) -> HealthStatus` in `health/profile_health.py` (independently unit-testable, no DB). Each participating signal maps to `green`/`yellow`/`red`; the overall status is the worst.

- **Success rate**: `< 0.5` → red; `< 0.9` → yellow; else green. (`SUCCESS_RED = 0.5`, `SUCCESS_YELLOW = 0.9`)
- **Unacked anomalies (7d)**: `>= 5` → red; `>= 1` → yellow; `0` → green. (`ANOMALY_RED = 5`, `ANOMALY_YELLOW = 1`)
- **Device pool** (only `android`/`agent_android` with ≥1 bound serial): `0` online → red; some-but-not-all online → yellow; all online → green. Non-android or unbound → signal not applicable, excluded.
- **Avg duration**: **display-only, does not drive color** — slow ≠ unhealthy, and duration outliers already flow in via the anomaly count (the Anomaly Center's duration detector), so counting it here would double-count.

Overall = worst of the participating signals (`red > yellow > green`).

Special case **⚪ nodata**: no terminal samples in the window → status `nodata` (grey), judged neither healthy nor unhealthy (no basis).

Thresholds are module constants for easy future tuning.

## API

Extend the existing profiles router (`api/profiles.py`):

- `GET /api/v1/profiles/health` → `list[ProfileHealth]`.

New schema `ProfileHealth` (`models/api.py`):

```python
class ProfileHealth(BaseModel):
    name: str
    platform: str
    status: str  # green | yellow | red | nodata
    success_rate: float | None   # None when nodata
    total_runs: int              # terminal samples in window
    avg_duration_ms: float | None
    unacked_anomalies: int
    devices_online: int | None   # None for non-android / unbound
    devices_total: int | None
```

## Frontend

- **Nav**: a "Profile 健康 Health" entry under 资源 (`AppLayout.tsx`, next to 配置档 Profiles).
- **Data layer** `web/src/api/profileHealth.ts`: `useProfileHealth()`. Types `ProfileHealth`, `HealthStatus` in `web/src/types/api.ts`.
- **Page** `web/src/pages/Profiles/Health.tsx` + route `profiles/health` in `App.tsx`:
  - Responsive card grid (AntD `Row`/`Col`). Each card: top status block (colored dot + profile name + platform Tag), then four metric rows (成功率 / 平均耗时 / 异常数 / 设备 x/y; non-android shows `—` for devices).
  - Cards sorted worst-first (`red > yellow > green > nodata`).
  - A summary bar above the grid: `N 健康 · M 警告 · K 异常 · J 无数据`.
  - Click-throughs: anomaly count → `/system/anomalies?target_profile=<name>` (Anomaly Center pre-filtered); card title → that profile's edit page (`/profiles/<name>`); device count (android only) → opens the existing `ProfileDeviceScreensModal` scoped to that profile's serials.
  - A "只看非健康" toggle (default off = show all).
  - `EmptyState`/`ErrorState` reused for empty/error.
- **Anomaly Center pre-filter**: `pages/System/Anomalies.tsx` reads `target_profile` from the URL query on mount to pre-fill its profile filter (currently filter state is component-only, no profile-name filter control exists — add a small profile filter fed by the URL). This is a small change carried by this feature.

## Error handling

- Health assembly is read-only aggregation; a failure in any single source query surfaces as the endpoint's error (standard 500 → frontend `ErrorState`), not a partial/misleading card grid.
- A profile with zero runs in the window renders a valid ⚪ nodata card, not an error or an omission.
- Division-by-zero in success rate is guarded (nodata when denominator 0).

## Testing

**Backend:**
- `compute_health` pure-function tests: each signal's red/yellow/green boundaries, worst-of selection, nodata special case, non-android skipping the device signal, avg-duration-not-driving-color.
- `success_stats_by_profile(since)` / `avg_duration_by_profile(since)` / `unacked_counts_by_profile(since)`: seed data, assert per-profile+window aggregation, and that out-of-window rows are excluded.
- `list_profile_health()` assembly: a multi-profile scenario (samples + anomalies + devices) → correct four-signal rollup and worst-first order.
- Endpoint integration test: auth, response shape, 7-day window boundary.

**Frontend:**
- `useProfileHealth` hook test.
- Health page component test: renders cards, worst-first order, summary bar, anomaly-count click navigates with `target_profile` query, "只看非健康" filter.
- Nav entry present.
- Anomaly Center reads URL `target_profile` and pre-fills its filter (regression test).
