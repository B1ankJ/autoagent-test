# Response Search Enhancements — Design

## Problem

The response search (shipped 2026-08-05) matches only responses (raw + LLM), with a single keyword box and a profile filter. In use, three gaps show up: you can't narrow to a time window, you can't restrict to certain sample statuses, and you sometimes want to find a phrase in the *prompt* too (or, conversely, keep prompt matches out when you only care about responses). All of these are pure retrieval refinements — no content judgement, consistent with the tool's positioning.

## Goals

- **Field scope**: choose whether the keyword matches all fields, responses only, or prompts only.
- **Status filter**: narrow to selected sample statuses.
- **Time-range filter**: narrow to samples finished within a window (`ended_at`).
- Keep the existing keyword + profile + pagination + snippet/highlight + URL-persisted state.

## Non-goals (this iteration)

- CSV/export of results (a separate candidate, not chosen here).
- Ranking/relevance (still substring LIKE, newest-first).
- Searching any field other than prompt/response/llm-response.

## Backend

Extend `storage/samples.py::search_samples_by_response` (all new params default to current behavior, so existing callers are unaffected):

```python
async def search_samples_by_response(
    q: str,
    target_profile: str | None = None,
    *,
    fields: str = "all",                 # "all" | "response" | "prompt"
    status: list[str] | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int,
    offset: int,
) -> tuple[list[SampleSearchHit], int]:
```

- **Field scope → LIKE clause** (`term = _like_term(q)`):
  - `all` → `prompts_sent_json LIKE term OR responses_json LIKE term OR llm_responses_json LIKE term`
  - `response` → `responses_json LIKE term OR llm_responses_json LIKE term`
  - `prompt` → `prompts_sent_json LIKE term`
  - An unrecognized `fields` value falls back to `all`.
- **Status** → `AND status IN (...)` when a non-empty list is given.
- **Time range** → `AND ended_at >= created_after` / `AND ended_at <= created_before` when given (samples with NULL `ended_at` are naturally excluded once a bound is set).
- **Ordering unchanged**: `ORDER BY ended_at DESC` (no `NULLS LAST` — see the SQLite portability convention).
- **Source determination** (`_first_match` + the per-row loop): check in scope order — if prompts are in scope and a prompt string contains `q` → `source="prompt"`; else raw responses → `"response"`; else LLM responses → `"llm_response"`. The snippet is cut from whichever string matched (same `_snippet` helper). `SampleSearchHit.source` gains `"prompt"` as a valid value (the schema field is a plain `str`, so no schema change needed — the TS union widens).

**Endpoint** `GET /api/v1/samples/search` gains query params (existing `q`/`target_profile`/`limit`/`offset` unchanged):
- `fields: str = "all"` (a small `Query` with the default; unrecognized → treated as `all` by the storage layer),
- `status: list[str] | None = Query(None)` (repeated param, `.in_()`),
- `created_after` / `created_before: datetime | None = None`.
It passes them straight through to `search_samples_by_response`.

## Frontend

`pages/Search/ResponseSearch.tsx` — the filter row gains three controls, all synced to the URL (same pattern as the existing `q`/`target_profile`/`page`, so navigating into a sample and back restores every filter):

- **范围 `Select`** — 全部字段 / 仅响应 / 仅 prompt → URL `fields` (omit when `all`).
- **状态 multi-select `Select`** — the `SampleStatus` options (done/failed/timeout/extraction_failed/queued/running/cancelled) → URL `status` as a comma-joined string, sent as repeated `status` query params (matching Batches List's multi-select convention).
- **时间 `RangePicker`** (with presets 最近 24 小时/7 天/30 天) → URL `created_after`/`created_before` (ISO).
- **来源列**: the source `Tag` renders a third value — `Prompt` (alongside 原始响应 / LLM 提取).

`api/search.ts`: `SampleSearchParams`/`useSampleSearch` gain `fields`, `status` (string[]), `createdAfter`, `createdBefore`; `buildSearchParams` forwards them (omitting empty/default). `SampleSearchHit.source` TS type widens to `'prompt' | 'response' | 'llm_response'`.

## Error handling

- Unknown `fields` value → backend treats as `all` (no 422 churn over a stale URL).
- A time bound with no `ended_at` rows → simply returns fewer/zero hits (not an error).
- All new filters are optional; the search still requires `q` ≥ 2 chars (unchanged) and is disabled client-side below that.

## Testing

**Backend:**
- `fields="prompt"` matches a prompt-only term and does NOT match a response-only term (and vice versa for `fields="response"`); `fields="all"` matches either; `source` is `"prompt"` when the prompt matched.
- `status` filter narrows to the given statuses.
- Time-range filter includes in-window, excludes out-of-window, and excludes NULL-`ended_at` rows when a bound is set.
- Combined filters (fields + status + time) compose (AND).
- Endpoint: the new params are accepted and forwarded; repeated `status` works; response shape unchanged.

**Frontend:**
- `buildSearchParams` forwards `fields`/`status`/`created_after`/`created_before` and omits them when empty/default.
- `useSampleSearch` still disabled below 2 chars.
- ResponseSearch renders the scope/status/range controls; changing each writes to the URL; the source Tag shows `Prompt` for a prompt hit; a URL carrying the new params restores them on mount.
