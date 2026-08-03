# Anomaly Center — Design

## Problem

Anomaly detection today is fragmented and mostly ephemeral:

- Three DingTalk rules (`notifications/rules.py`: empty-response streak, same-response streak via VLM, ANR) fire per-sample and **push to DingTalk only** — they leave no in-app trace, so there's no way to browse "what anomalies happened this week" without scrolling a chat group.
- The one in-app anomaly signal, `storage/batches.py::is_duration_anomaly`, is a fixed-ratio heuristic (a single-sample batch whose duration is >2×/<0.5× the profile's *mean*) rendered as a passive per-row flag on Batches List. Mean-ratio is statistically wrong for right-skewed latency data, and it's display-only — not queryable, not manageable.

There is no single place to see, filter, and triage anomalies.

## Goals

- A statistically principled duration-outlier detector (IQR fences over the profile's recent history) that **persists** each anomaly as a record.
- A unified `anomalies` table that the new detector **and** the three existing DingTalk rules both write to, so every anomaly leaves an in-app trace.
- A web "异常中心 Anomalies" page: list, filter (type / profile / acknowledged), acknowledge (single + bulk), and click through to the triggering sample's detail page. A nav badge showing the unacknowledged count.

## Non-goals (this iteration)

- Response-length and batch-success-rate detectors (deferred — duration only this cut).
- Replacing or changing the existing `is_duration_anomaly` flag on Batches List (it stays as a fast at-a-glance ratio hint; the Anomaly Center is the deeper statistical view — a note, not a change, this iteration).
- New DingTalk pushes for duration anomalies (duration stays push-free / panel-only, as it has always been; the three rules keep their existing pushes and *additionally* write records).
- Per-anomaly severity levels, cross-profile baselines, or configurable IQR multiplier (fixed 1.5 this cut).

## Data model

New table `anomalies` (`models/db.py`, Alembic migration per CLAUDE.md's migration workflow):

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK autoincrement | |
| `type` | String, indexed | `duration` \| `empty_streak` \| `same_response` \| `anr` |
| `batch_id` | String, indexed | triggering batch |
| `sample_id` | String, indexed | triggering sample (streak rules use the latest sample in the streak) |
| `target_profile` | String, indexed | |
| `device_serial` | String, nullable | |
| `summary` | Text | human-readable one-liner, e.g. `耗时 8.2s，高于 P75+1.5·IQR 阈值 6.1s` |
| `detail_json` | Text (JSON) | structured payload (per-type shape below) |
| `acknowledged` | Boolean, indexed, default False, server_default | |
| `acknowledged_at` | DateTime, nullable | |
| `created_at` | DateTime, indexed, server_default now | |

`detail_json` shapes:
- `duration`: `{value, q1, q3, iqr, fence_low, fence_high, direction: "high"|"low", sample_count}`
- `empty_streak`: `{streak_count, response}`
- `same_response`: `{streak_count, response}`
- `anr`: `{package}`

Because SQLite can't add a non-null column to a non-empty table without a default, `acknowledged` gets a `server_default` in the migration (existence-guarded per the repo's Alembic conventions).

API schema `AnomalyRecord` (`models/api.py`): mirrors the columns, `detail` as a `dict`, `created_at`/`acknowledged_at` as ISO datetimes.

## Module structure

New package `src/autoagent/anomalies/` (keeps this out of the already-684-line `rules.py`):

- `store.py` — the single write/read/ack layer over the `anomalies` table:
  - `async record_anomaly(*, type, batch_id, sample_id, target_profile, device_serial, summary, detail) -> None`
  - `async list_anomalies(*, type=None, target_profile=None, acknowledged=None, limit, offset) -> tuple[list[AnomalyRecord], int]` (rows + total, newest first)
  - `async acknowledge(anomaly_id) -> bool` (idempotent; False if id absent)
  - `async count_unacknowledged() -> int`
  - `async delete_for_batch(batch_id) -> int`
- `duration_detector.py`:
  - Pure function `evaluate_duration(value: int, history: list[int]) -> DurationVerdict | None` — the IQR math, fully unit-testable with no DB.
  - `async check_duration_anomaly(result: SampleResult, batch_id: str) -> None` — the scheduler hook: pulls the profile's recent timed durations, runs `evaluate_duration`, calls `record_anomaly` on a hit.

## Detection

### Statistical duration detector (IQR fences)

`evaluate_duration(value, history)`:
1. If `len(history) < MIN_HISTORY` (20) → return `None` (baseline untrustworthy).
2. Compute Q1, Q3 (linear-interpolation percentiles, `statistics.quantiles(history, n=4)` gives the three quartile cut points), `IQR = Q3 − Q1`.
3. `fence_high = Q3 + 1.5·IQR`, `fence_low = Q1 − 1.5·IQR`.
4. `value > fence_high` → `direction="high"`; `value < fence_low` → `direction="low"`; else `None`.
5. Return `{value, q1, q3, iqr, fence_low, fence_high, direction, sample_count=len(history)}`.

`check_duration_anomaly(result, batch_id)`:
- Only runs when `result.duration_ms` is set (a real timed sample — skips end_session no-ops, cancelled, device-acquisition failures, same as `avg_duration_by_profile`).
- Baseline = the profile's **most recent N=500** timed durations (new `storage/samples.py::recent_durations_for_profile(profile, limit=500)` — `WHERE duration_ms IS NOT NULL AND target_profile=? ORDER BY created_at DESC LIMIT 500`, returns the duration ints). Bounds the query cost (SQLite has no percentile function, so the list is pulled and IQR computed in Python) and keeps the baseline current as a profile drifts.
- On a verdict, `record_anomaly(type="duration", ..., summary=<formatted>, detail=<verdict dict>)`. No DingTalk push.

Wired into `scheduler/batch_scheduler.py::run_one` right where `_notify_on_sample(result, batch_id)` is already awaited (both run at sample completion, after `session_id`/`new_session` are stamped). A detector failure must never crash the sample — wrapped in try/except with a `log.exception`, same defensive posture as the notify hook.

### The three DingTalk rules write records

In `notifications/rules.py`, each of `_fire_empty_streak_alert`, `_fire_same_response_alert`, `_fire_anr_alert` calls `record_anomaly(...)` alongside its existing `send_markdown(...)` — behavior otherwise unchanged. The streak rules reference the latest sample in the streak; ANR references the current sample. Each writes its own `type` and `detail` shape.

## API

New router `api/anomalies.py`, mounted at `/api/v1` (bearer-auth like the rest):

- `GET /api/v1/anomalies` — params `type`, `target_profile`, `acknowledged` (default unset = all; UI sends `false` by default), `limit` (≤200, matching the batches cap), `offset`. Returns `{items: AnomalyRecord[], total}`, newest first.
- `GET /api/v1/anomalies/count?acknowledged=false` — `{count}` for the nav badge (cheap; no row payload).
- `POST /api/v1/anomalies/{id}/acknowledge` — sets `acknowledged=true`, `acknowledged_at=now`; idempotent; 404 if the id doesn't exist.

No bulk-acknowledge endpoint — the frontend fans out `Promise.allSettled` over the single endpoint (the established Devices/Batches bulk-op pattern in this repo).

## Retention

Anomalies reference a batch/sample; they inherit the batch's lifecycle. `storage/batches.py::delete_batch_rows` (the single delete path used by both manual delete and `maintenance/batch_retention.py`) gains a `DELETE FROM anomalies WHERE batch_id=?` (via `store.delete_for_batch`) so records never outlive their batch and can't accumulate unbounded. No separate retention job.

## Frontend

- **Nav**: a "异常中心 Anomalies" entry under 系统 (`AppLayout.tsx`, next to 运行日志), with a count Badge fed by `useAnomalyCount()` (`GET /anomalies/count?acknowledged=false`) — same badge mechanism already used for the Batches running-count.
- **Data layer** `web/src/api/anomalies.ts`: `useAnomalies(filters)`, `useAcknowledgeAnomaly()`, `useAnomalyCount()`. Types in `web/src/types/api.ts` (`AnomalyRecord`, `AnomalyType`).
- **Page** `web/src/pages/System/Anomalies.tsx` + route `system/anomalies` in `App.tsx`:
  - Filter controls: type (multi-select), profile, an 未处理/全部 toggle (default 未处理).
  - AntD Table: 时间 / 类型 (colored Tag) / profile / 设备 / 摘要 / 操作. Per-row 确认 button + a checkbox-selection toolbar 批量确认 (`Promise.allSettled` over the single ack endpoint). Column widths via the existing `useResizableColumns`.
  - Each row links through to `/batches/{batch_id}/samples/{sample_id}` (reuses the existing sample detail page with screenshots/action log).
  - `EmptyState`/`ErrorState` for empty/error, matching other pages.

## Error handling

- Detector/record-write failures are caught and logged (`log.exception`) so they never crash a sample run or a rule's alert.
- `evaluate_duration` returns `None` (no anomaly) rather than raising on too-little history or degenerate input (all-equal durations → IQR 0 → fences equal the quartiles → only strictly-outside values flag, which is correct).
- Ack of a non-existent id → 404; ack of an already-acked id → 200 (idempotent).

## Testing

**Backend:**
- `evaluate_duration` pure-function unit tests: min-history guard, high/low/normal verdicts, all-equal-history edge (IQR 0), exact-fence boundary.
- `store` unit tests: record → list (filters: type/profile/acknowledged) → acknowledge → count_unacknowledged → delete_for_batch, against a fresh test DB.
- `check_duration_anomaly` writes a record for an outlier and nothing when history is too small (with a seeded profile history).
- Endpoint integration tests: list + filters + pagination cap, count, acknowledge (200 + idempotent + 404).
- Each of the three rules writes an anomaly record when it fires (extend existing rule tests).
- `delete_batch_rows` removes the batch's anomalies.

**Frontend:**
- `useAnomalies`/`useAcknowledgeAnomaly`/`useAnomalyCount` hook tests.
- Anomalies page component test: renders rows, type/acknowledged filter, single ack, bulk ack, click-through navigation.
- Nav badge shows the unacknowledged count.
