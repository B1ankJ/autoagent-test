# Anomaly Center Enhancements — Design

## Problem

The anomaly center (shipped 2026-08-03) has three gaps that surfaced in real use:

1. **No time filter** — the list can only filter by type/profile/acknowledged, so "what anomalies happened last night" means scrolling.
2. **No historical backfill** — the duration detector is a per-sample hook that only fires on new runs (and needs ≥20 prior timed samples + an IQR outlier). A freshly-deployed system shows an empty anomaly center even with lots of history, which reads as "broken" (it isn't — there's just nothing computed yet).
3. **No push digest** — anomalies accrue silently; without watching the page, you don't know a profile started producing anomalies.

## Goals

- Filter the anomaly list by a `created_at` time range (with quick presets).
- A manual, idempotent historical backfill that scans past samples through the same IQR duration detector and records the anomalies it finds.
- An opt-in periodic DingTalk digest of newly-created anomalies (since the last digest), reusing the existing DingTalk channel.

## Non-goals (this iteration)

- Backfilling the streak/ANR rule anomalies (those need live device/log state that no longer exists for historical samples — only the duration detector is backfillable, since it works purely from stored `duration_ms`).
- A background-job/polling system for backfill (it runs synchronously — it's a rare admin action and fast in practice: pure Python iteration + a bounded number of inserts).
- Alerting channels beyond the existing DingTalk webhook.
- Health-trend time series (that's the separate "health trends" sub-project).

## Part 1 — Time-range filter

**Backend** (`anomalies/store.py`, `api/anomalies.py`): `list_anomalies` and `GET /api/v1/anomalies` gain optional `created_after` / `created_before` (ISO datetimes) → `WHERE created_at >= created_after AND created_at <= created_before`, composed with the existing type/profile/acknowledged filters.

**Frontend** (`pages/System/Anomalies.tsx`, `api/anomalies.ts`): the filter row gains an AntD `RangePicker` with quick presets (最近 1 小时 / 24 小时 / 7 天 / 30 天). Selecting a range feeds `created_after`/`created_before` into the `AnomalyFilters` (extended with those two fields; `buildAnomalyParams` forwards them). Clearing it = no time bound. Filter state is component-local, consistent with the existing type/acknowledged filters.

## Part 2 — Historical backfill

**New module `src/autoagent/anomalies/backfill.py`**: `async backfill_duration_anomalies() -> BackfillResult` where `BackfillResult` is a small dataclass `(scanned: int, created: int)`.

Algorithm:
- Load the set of `sample_id`s that already have a `type="duration"` anomaly (new `store.existing_duration_sample_ids() -> set[str]`) — the dedup key. Each sample produces at most one duration anomaly, so this makes re-running idempotent and prevents duplicating anomalies the live detector already created.
- For each profile, load its timed samples (`duration_ms IS NOT NULL`) ordered by `ended_at` ascending via a new `storage/samples.py::timed_samples_for_profile(profile) -> list[TimedSample]`, where `TimedSample` carries `sample_id`, `batch_id`, `duration_ms`, and `device_serial` (the last parsed best-effort from the row's `metadata_json` — the same place the live hook reads `metadata.get("device_serial")`; `None` when absent).
- Slide through them **point-in-time**: for sample *i*, the baseline is the durations of the samples *before* it (respecting `MIN_HISTORY=20` before evaluating and the 500-sample recency cap), fed to the existing `evaluate_duration`. This matches the live detector's definition exactly (a sample is judged against what preceded it), so backfilled anomalies use the same IQR contract as live ones.
- Skip any sample already in the dedup set. For a hit not in the set, `store.record_anomaly(type="duration", ...)` with the same `summary`/`detail` shape the live hook produces (reuse the live hook's `_format_summary`).
- `scanned` counts samples evaluated; `created` counts anomalies recorded.

**Endpoint** `POST /api/v1/anomalies/backfill` (admin, inherits the router-level `require_user`): runs `backfill_duration_anomalies()` synchronously and returns `{"scanned": N, "created": M}`.

**Frontend** (Config page): a "扫描历史生成异常" button in the DingTalk/anomaly settings area → calls the endpoint → `message.success("扫描 N 条，新增 M 条异常")`. A confirming Popconfirm isn't needed (it's additive and idempotent), but the button shows a loading state while running.

## Part 3 — Periodic DingTalk digest

**Config** (`DingTalkNotificationConfig` in `models/api.py`): new field `digest_interval_hours: int = 0` (0 = off, default off). The digest reuses the existing `enabled`/`webhook_url`/`secret`; it sends only when `enabled and webhook_url and digest_interval_hours > 0`.

**State**: the "last digest sent at" timestamp is persisted to a kv config key (`anomaly_digest_state`, same `get_config`/`put_config` mechanism `notifications/rules.py` uses for `notification_state`) so "since last digest" is stable across restarts.

**Loop** (`maintenance/scheduler.py::run_digest_loop()`, wired into `main.py`'s lifespan alongside `run_backup_loop`/`run_retention_loop`): startup delay, then each tick reads `digest_interval_hours` from config (like `run_backup_loop` reads `backup_interval_hours`). When enabled and the interval has elapsed since the last digest:
- Gather anomalies created since the last-digest timestamp (`store.anomalies_created_since(since) -> list[AnomalyRecord]`).
- If **zero** new anomalies → skip sending (no "all clear" noise), but still advance the timestamp so the window doesn't grow unbounded.
- Otherwise build a DingTalk markdown (a pure function `build_digest_markdown(anomalies, since, app_base_url) -> str` — grouped counts by type and by profile, total, and the top few example summaries with sample links via the existing `_sample_ref_md`), send it via `notifications/dingtalk.py::send_markdown`, and on success advance the timestamp.

**Frontend** (Config page): the DingTalk settings section gains the `digest_interval_hours` numeric field (0 = 关闭).

## Data flow summary

- Time filter: RangePicker → `AnomalyFilters` → `GET /anomalies?created_after=&created_before=` → `list_anomalies` `WHERE created_at BETWEEN`.
- Backfill: Config button → `POST /anomalies/backfill` → `backfill_duration_anomalies` (dedup set + per-profile point-in-time slide + `evaluate_duration` + `record_anomaly`) → `{scanned, created}`.
- Digest: `run_digest_loop` tick → `anomalies_created_since(last)` → `build_digest_markdown` → `send_markdown` → advance `anomaly_digest_state`.

## Error handling

- The digest loop's tick is wrapped so a transient failure (DB read, webhook down) doesn't kill the loop task (same posture as `run_backup_loop`/`run_retention_loop`); a failed `send_markdown` does **not** advance the timestamp, so the next tick retries the same window.
- Backfill is idempotent: a crash mid-run or a re-click never double-records (dedup set is re-read each run).
- Time-filter params are optional; malformed datetimes are rejected by FastAPI's query parsing (422), same as other datetime query params in the codebase.

## Testing

**Backend:**
- `list_anomalies` with `created_after`/`created_before`: in-window rows returned, out-of-window excluded, composes with other filters.
- `backfill_duration_anomalies`: point-in-time slide flags the right outlier(s); respects `MIN_HISTORY`; dedup skips samples that already have a duration anomaly; re-running is idempotent (`created==0` the second time); `scanned`/`created` counts correct.
- `existing_duration_sample_ids` / `timed_samples_for_profile` / `anomalies_created_since` unit tests.
- `build_digest_markdown` pure-function test: grouped counts, top-N examples, correct total.
- `run_digest_loop` tick: enabled + new anomalies → sends + advances timestamp; zero new → skips send but advances; send failure → does not advance.
- Endpoint integration: `POST /anomalies/backfill` returns counts and actually creates records; `GET /anomalies` time params.

**Frontend:**
- `buildAnomalyParams` forwards `created_after`/`created_before`; the page feeds the RangePicker selection into the filters.
- Config backfill button calls the endpoint and shows the result count.
- Config renders/saves the `digest_interval_hours` field.
