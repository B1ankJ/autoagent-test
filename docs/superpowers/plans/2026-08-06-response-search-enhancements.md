# Response Search Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add field-scope (all/response/prompt), status filter, and a time-range filter to the response search — backend params + storage query, plus URL-synced frontend controls.

**Architecture:** Extend `storage/samples.py::search_samples_by_response` and the `api/search.py` endpoint with the new (backward-compatible) params; extend `web/src/api/search.ts` and add three URL-synced controls to `ResponseSearch.tsx`.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (SQLite), `uv`; React 18 + TS + AntD 5, TanStack Query, Vitest.

---

## Context an implementer needs

- **Current `search_samples_by_response(q, target_profile=None, *, limit, offset)`** (`storage/samples.py`): LIKEs `responses_json OR llm_responses_json` (escaped via local `_like_term`), `ORDER BY ended_at DESC` (deliberately **no** `.nullslast()` — SQLite <3.30 portability), and per row picks `source` (`response` if `_first_match(raw, q)` else `llm_response`) + `_snippet(matched, q)`. `_first_match(items, q)` returns the first string in the list containing `q` (case-insensitive) or None.
- **`Sample` columns**: `prompts_sent_json`, `responses_json`, `llm_responses_json` (JSON arrays, `ensure_ascii=False`), `status`, `target_profile`, `ended_at`. `SampleSearchHit.source` is a plain `str` (Pydantic) — adding `"prompt"` needs no schema change.
- **Endpoint** `api/search.py`: `GET /samples/search` with `q=Query(..., min_length=2)`, `target_profile`, `limit=Query(50, ge=1, le=200)`, `offset`. Router has `dependencies=[Depends(require_user)]`. For a repeated list param use `status: list[str] | None = Query(None)`.
- **Frontend `api/search.ts`**: `useSampleSearch({ q, targetProfile, page, pageSize })` inlines its params in the queryFn today — this plan extracts a pure `buildSearchParams` (mirrors `buildAnomalyParams`) for testability. axios serializes an array param (`status: [...]`) as repeated `status=a&status=b`, matching FastAPI's `list[str]`.
- **`ResponseSearch.tsx`** already keeps `q`/`target_profile`/`page` in the URL via `useSearchParams` + a `patch()` helper; the new controls follow the same pattern. It renders a filter `Space` with `Input.Search` + a profile `Select`, and a source `Tag` (`llm_response` → 'LLM 提取' else '原始响应').
- **Types**: `SampleSearchHit` in `web/src/types/api.ts` has `source: 'response' | 'llm_response'`; `SampleStatus` is exported there.
- **Tests**: backend `pytest-asyncio` auto mode, `await init_db()`. `tests/unit/test_response_search.py` and `tests/integration/test_search_endpoint.py` exist — extend them. Run `uv run pytest -q <path>`; lint `uv run ruff check <files>; echo EXIT=$?`. Frontend `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run <path>`, `pnpm exec tsc --noEmit`, `pnpm lint`. pnpm cwd resets → prefix `cd .../web &&`.

---

## File Structure

- Modify `src/autoagent/storage/samples.py` (extend `search_samples_by_response` + source picking)
- Modify `src/autoagent/api/search.py` (new query params)
- Modify `web/src/types/api.ts` (`source` union), `web/src/api/search.ts` (`buildSearchParams` + extended params)
- Modify `web/src/pages/Search/ResponseSearch.tsx` (scope/status/range controls + Prompt tag)
- Tests: `tests/unit/test_response_search.py`, `tests/integration/test_search_endpoint.py`; frontend `web/src/api/search.test.ts` (new), `web/src/pages/Search/ResponseSearch.test.tsx`

---

## Task 1: Backend query — fields / status / time / prompt source

**Files:** Modify `src/autoagent/storage/samples.py`; Test `tests/unit/test_response_search.py`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_response_search.py`:

```python
@pytest.mark.asyncio
async def test_search_fields_scope():
    await init_db()
    now = datetime.now(timezone.utc)
    # prompt-only match
    await upsert_sample(
        "b",
        SampleResult(id="pq", status="done", mode="api", target_profile="p",
                     prompts_sent=["问一下 唯一词A"], responses=["无关"], ended_at=now),
    )
    # response-only match
    await upsert_sample(
        "b",
        SampleResult(id="rq", status="done", mode="api", target_profile="p",
                     prompts_sent=["无关"], responses=["答案 唯一词A"], ended_at=now),
    )

    # fields=all → both
    _, all_total = await search_samples_by_response("唯一词A", fields="all", limit=20, offset=0)
    assert all_total == 2
    # fields=prompt → only the prompt hit, source="prompt"
    p_hits, p_total = await search_samples_by_response("唯一词A", fields="prompt", limit=20, offset=0)
    assert p_total == 1 and p_hits[0].sample_id == "pq" and p_hits[0].source == "prompt"
    assert "唯一词A" in p_hits[0].snippet
    # fields=response → only the response hit
    r_hits, r_total = await search_samples_by_response("唯一词A", fields="response", limit=20, offset=0)
    assert r_total == 1 and r_hits[0].sample_id == "rq" and r_hits[0].source == "response"


@pytest.mark.asyncio
async def test_search_status_filter():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="d", status="done", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=now))
    await upsert_sample("b", SampleResult(id="f", status="failed", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=now))
    _, total = await search_samples_by_response("找我", status=["failed"], limit=20, offset=0)
    assert total == 1


@pytest.mark.asyncio
async def test_search_time_range_filter():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="recent", status="done", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=now))
    await upsert_sample("b", SampleResult(id="old", status="done", mode="api",
                                          target_profile="p", responses=["找我"],
                                          ended_at=now - timedelta(days=30)))
    await upsert_sample("b", SampleResult(id="none", status="done", mode="api",
                                          target_profile="p", responses=["找我"], ended_at=None))
    _, total = await search_samples_by_response(
        "找我", created_after=now - timedelta(days=7), limit=20, offset=0
    )
    assert total == 1  # only the recent one (old + null excluded)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_response_search.py -k "fields_scope or status_filter or time_range"`
Expected: FAIL — `search_samples_by_response` got unexpected keyword `fields`.

- [ ] **Step 3: Implement** — in `src/autoagent/storage/samples.py`, replace the `search_samples_by_response` signature/body. Add a `_pick_source` helper above it:

```python
def _match_columns(fields: str):
    """Columns the keyword LIKEs against, by scope."""
    if fields == "prompt":
        return [SampleRow.prompts_sent_json]
    if fields == "response":
        return [SampleRow.responses_json, SampleRow.llm_responses_json]
    return [SampleRow.prompts_sent_json, SampleRow.responses_json, SampleRow.llm_responses_json]


def _pick_source(row, q: str, fields: str) -> tuple[str, str]:
    """Return (source, matched_string) — checks prompt/raw/llm in scope order."""
    import json as _json

    if fields != "response":
        m = _first_match(_json.loads(row.prompts_sent_json or "[]"), q)
        if m is not None:
            return "prompt", m
    if fields != "prompt":
        m = _first_match(_json.loads(row.responses_json or "[]"), q)
        if m is not None:
            return "response", m
        m = _first_match(_json.loads(row.llm_responses_json or "[]"), q)
        if m is not None:
            return "llm_response", m
    return ("prompt" if fields == "prompt" else "response"), ""


async def search_samples_by_response(
    q: str,
    target_profile: str | None = None,
    *,
    fields: str = "all",
    status: list[str] | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int,
    offset: int,
) -> tuple[list[SampleSearchHit], int]:
    """Cross-batch search over prompt/response/llm-response content (substring
    LIKE, escaped), scoped by `fields` (all|response|prompt), optionally
    filtered by status and ended_at range. Newest first, with a snippet + the
    matched source, plus a total count."""
    term = _like_term(q)
    cols = _match_columns(fields)
    match = cols[0].like(term, escape="\\")
    for c in cols[1:]:
        match = match | c.like(term, escape="\\")

    sm = get_sessionmaker()
    async with sm() as s:
        conds = [match]
        if target_profile is not None:
            conds.append(SampleRow.target_profile == target_profile)
        if status:
            conds.append(SampleRow.status.in_(status))
        if created_after is not None:
            conds.append(SampleRow.ended_at >= created_after)
        if created_before is not None:
            conds.append(SampleRow.ended_at <= created_before)
        total = (
            await s.execute(select(func.count()).select_from(SampleRow).where(*conds))
        ).scalar_one()
        rows = (
            (
                await s.execute(
                    select(SampleRow)
                    .where(*conds)
                    .order_by(SampleRow.ended_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        hits: list[SampleSearchHit] = []
        for r in rows:
            source, matched = _pick_source(r, q, fields)
            hits.append(
                SampleSearchHit(
                    batch_id=r.batch_id,
                    sample_id=r.id,
                    target_profile=r.target_profile,
                    status=r.status,
                    ended_at=r.ended_at.replace(tzinfo=timezone.utc) if r.ended_at else None,
                    source=source,
                    snippet=_snippet(matched, q),
                )
            )
        return hits, int(total)
```

(The old inline `json.loads(...)`/`_first_match` block in the loop is replaced by `_pick_source`. `_first_match` stays as-is.)

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_response_search.py`
Expected: PASS (all — the pre-existing tests still pass since defaults are unchanged).

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/storage/samples.py tests/unit/test_response_search.py; echo "EXIT=$?"
git add src/autoagent/storage/samples.py tests/unit/test_response_search.py
git commit -m "feat(search): add field-scope, status, and time-range filters to response search"
```

---

## Task 2: Endpoint params

**Files:** Modify `src/autoagent/api/search.py`; Test `tests/integration/test_search_endpoint.py`.

- [ ] **Step 1: Write the failing test** — append to `tests/integration/test_search_endpoint.py`:

```python
@pytest.mark.asyncio
async def test_search_endpoint_new_params(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="pq", status="done", mode="api",
                                          target_profile="p", prompts_sent=["提示 关键字K"],
                                          responses=["无关"], ended_at=now))
    await upsert_sample("b", SampleResult(id="rq", status="failed", mode="api",
                                          target_profile="p", prompts_sent=["无关"],
                                          responses=["答案 关键字K"], ended_at=now))

    # fields=prompt → only the prompt hit
    r = await client.get("/api/v1/samples/search?q=关键字K&fields=prompt", headers=h)
    assert r.json()["total"] == 1 and r.json()["items"][0]["source"] == "prompt"
    # status=failed → only the failed one
    r = await client.get("/api/v1/samples/search?q=关键字K&status=failed", headers=h)
    assert r.json()["total"] == 1 and r.json()["items"][0]["sample_id"] == "rq"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_search_endpoint.py -k new_params`
Expected: FAIL — `fields`/`status` ignored (total 2, not 1).

- [ ] **Step 3: Implement** — in `src/autoagent/api/search.py`, extend the route. Add `from datetime import datetime` at the top:

```python
@router.get("/search", response_model=SampleSearchResponse)
async def search_responses(
    q: str = Query(..., min_length=2),
    target_profile: str | None = None,
    fields: str = "all",
    status: list[str] | None = Query(None),
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SampleSearchResponse:
    items, total = await search_samples_by_response(
        q.strip(),
        target_profile=target_profile,
        fields=fields,
        status=status,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        offset=offset,
    )
    return SampleSearchResponse(items=items, total=total)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_search_endpoint.py`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/api/search.py tests/integration/test_search_endpoint.py; echo "EXIT=$?"
git add src/autoagent/api/search.py tests/integration/test_search_endpoint.py
git commit -m "feat(search): accept fields/status/time params on /samples/search"
```

---

## Task 3: Frontend data layer

**Files:** Modify `web/src/types/api.ts`, `web/src/api/search.ts`; Test `web/src/api/search.test.ts` (new).

- [ ] **Step 1: Widen the source type** in `web/src/types/api.ts`:

```ts
  source: 'prompt' | 'response' | 'llm_response'
```

- [ ] **Step 2: Write the failing test** — create `web/src/api/search.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildSearchParams } from './search'

describe('buildSearchParams', () => {
  it('always sends q/limit/offset and omits empty/default filters', () => {
    expect(buildSearchParams({ q: 'hi', page: 1 })).toEqual({ q: 'hi', limit: 20, offset: 0 })
  })

  it('forwards the set filters and computes offset', () => {
    expect(
      buildSearchParams({
        q: 'hi',
        page: 2,
        pageSize: 10,
        targetProfile: 'p',
        fields: 'prompt',
        status: ['failed', 'done'],
        createdAfter: '2026-08-01T00:00:00Z',
        createdBefore: '2026-08-06T00:00:00Z',
      }),
    ).toEqual({
      q: 'hi',
      limit: 10,
      offset: 10,
      target_profile: 'p',
      fields: 'prompt',
      status: ['failed', 'done'],
      created_after: '2026-08-01T00:00:00Z',
      created_before: '2026-08-06T00:00:00Z',
    })
  })

  it('omits fields when "all" and status when empty', () => {
    expect(buildSearchParams({ q: 'hi', page: 1, fields: 'all', status: [] })).toEqual({
      q: 'hi',
      limit: 20,
      offset: 0,
    })
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/api/search.test.ts`
Expected: FAIL — `buildSearchParams` not exported.

- [ ] **Step 4: Implement** — rewrite `web/src/api/search.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { SampleSearchResponse } from '../types/api'
import { client } from './client'

export interface SampleSearchParams {
  q: string
  targetProfile?: string
  fields?: string
  status?: string[]
  createdAfter?: string
  createdBefore?: string
  page: number
  pageSize?: number
}

export function buildSearchParams(
  p: SampleSearchParams,
): Record<string, string | number | string[]> {
  const pageSize = p.pageSize ?? 20
  const out: Record<string, string | number | string[]> = {
    q: p.q.trim(),
    limit: pageSize,
    offset: (p.page - 1) * pageSize,
  }
  if (p.targetProfile) out.target_profile = p.targetProfile
  if (p.fields && p.fields !== 'all') out.fields = p.fields
  if (p.status && p.status.length) out.status = p.status
  if (p.createdAfter) out.created_after = p.createdAfter
  if (p.createdBefore) out.created_before = p.createdBefore
  return out
}

export function useSampleSearch(params: SampleSearchParams) {
  const trimmed = params.q.trim()
  return useQuery({
    queryKey: ['samples', 'search', buildSearchParams(params)],
    enabled: trimmed.length >= 2,
    queryFn: async () =>
      (await client.get<SampleSearchResponse>('/samples/search', { params: buildSearchParams(params) }))
        .data,
  })
}
```

- [ ] **Step 5: Run to verify it passes + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/api/search.test.ts && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean.

- [ ] **Step 6: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/types/api.ts web/src/api/search.ts web/src/api/search.test.ts
git commit -m "feat(web): extend the search data layer with scope/status/time params"
```

---

## Task 4: ResponseSearch controls (scope / status / range) + Prompt tag

**Files:** Modify `web/src/pages/Search/ResponseSearch.tsx`, `web/src/pages/Search/ResponseSearch.test.tsx`.

- [ ] **Step 1: Write the failing test** — add to `web/src/pages/Search/ResponseSearch.test.tsx`. First ensure the mocked `useSampleSearch` captures its args (it already forwards via `(...a) => useSampleSearch(...a)`). Add:

```tsx
it('renders the Prompt source tag and restores scope/status/time from the URL', async () => {
  useSampleSearch.mockReturnValue({
    data: {
      items: [hit({ sample_id: 's1', source: 'prompt' })],
      total: 1,
    },
    isLoading: false,
    isError: false,
  })
  renderWithProviders(
    <Routes>
      <Route path="/search/responses" element={<ResponseSearch />} />
    </Routes>,
    { initialPath: '/search/responses?q=abc&fields=prompt&status=failed' },
  )
  await waitFor(() => expect(screen.getByText('Prompt')).toBeInTheDocument())
  const args = useSampleSearch.mock.calls.at(-1)?.[0] as
    | { fields?: string; status?: string[] }
    | undefined
  expect(args?.fields).toBe('prompt')
  expect(args?.status).toEqual(['failed'])
})
```

(`hit(...)` already exists in the test file; it accepts `source` via the `Partial<SampleSearchHit>` spread.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Search/ResponseSearch.test.tsx`
Expected: FAIL — the URL's `fields`/`status` aren't read (args undefined) and no 'Prompt' tag.

- [ ] **Step 3: Implement** — in `web/src/pages/Search/ResponseSearch.tsx`:
  - Imports: add `DatePicker` to the antd import and `import dayjs, { Dayjs } from 'dayjs'`; add `SampleStatus` to the types import.
  - Read the new URL params (alongside the existing `q`/`profile`/`page`):
    ```tsx
    const fields = params.get('fields') ?? 'all'
    const status = (params.get('status') ?? '').split(',').filter(Boolean)
    const createdAfter = params.get('created_after') ?? undefined
    const createdBefore = params.get('created_before') ?? undefined
    ```
  - Pass them into the hook:
    ```tsx
    const { data, isLoading, isError, refetch } = useSampleSearch({
      q, targetProfile: profile, fields, status, createdAfter, createdBefore, page, pageSize,
    })
    ```
  - Source tag — extend the render:
    ```tsx
    render: (s: string) => (
      <Tag>{s === 'prompt' ? 'Prompt' : s === 'llm_response' ? 'LLM 提取' : '原始响应'}</Tag>
    ),
    ```
  - Add the three controls to the filter `Space` (after the profile `Select`):
    ```tsx
    <Select
      style={{ width: 130 }}
      value={fields}
      onChange={(v) => patch({ fields: v === 'all' ? undefined : v, page: undefined })}
      options={[
        { value: 'all', label: '全部字段' },
        { value: 'response', label: '仅响应' },
        { value: 'prompt', label: '仅 Prompt' },
      ]}
    />
    <Select
      mode="multiple"
      allowClear
      placeholder="全部状态"
      style={{ minWidth: 180 }}
      value={status}
      onChange={(v: string[]) => patch({ status: v.length ? v.join(',') : undefined, page: undefined })}
      options={(['done', 'failed', 'timeout', 'extraction_failed', 'cancelled'] as SampleStatus[]).map(
        (s) => ({ value: s, label: s }),
      )}
    />
    <DatePicker.RangePicker
      showTime
      value={
        createdAfter && createdBefore ? [dayjs(createdAfter), dayjs(createdBefore)] : null
      }
      onChange={(v) =>
        patch({
          created_after: v?.[0]?.toISOString(),
          created_before: v?.[1]?.toISOString(),
          page: undefined,
        })
      }
      presets={[
        { label: '最近 24 小时', value: [dayjs().add(-24, 'h'), dayjs()] },
        { label: '最近 7 天', value: [dayjs().add(-7, 'd'), dayjs()] },
        { label: '最近 30 天', value: [dayjs().add(-30, 'd'), dayjs()] },
      ]}
    />
    ```
  Confirm `patch` already deletes a key when its value is `undefined` (it does — `if (v) merged.set else merged.delete`). Note `createdAfter`/`createdBefore` are the camelCase local reads of the snake_case URL keys; the `patch` calls write the snake_case URL keys (`created_after`/`created_before`), so keep those exact key names in `patch({...})`.

- [ ] **Step 4: Run test + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Search/ResponseSearch.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean.

- [ ] **Step 5: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/Search/ResponseSearch.tsx src/pages/Search/ResponseSearch.test.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Search/ResponseSearch.tsx web/src/pages/Search/ResponseSearch.test.tsx
git commit -m "feat(web): add scope/status/time filters to the response search page"
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

- [ ] **Step 3: CLAUDE.md changelog entry** — extend the response-search bullet (or add a new one) documenting the field-scope (all/response/prompt), status filter, and ended_at time-range filter, all URL-synced. Reference the spec + this plan.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the response search enhancements"
```

- [ ] **Step 5: Push + verify CI** — user pre-authorized. Push and confirm CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`. If the frontend job dies with no log (the known transient recharts-era runner kill), re-run the failed job once before treating it as a real failure.

---

## Self-Review

**1. Spec coverage:**
- Field scope (all/response/prompt) → LIKE columns + source order → Task 1 (`_match_columns`/`_pick_source`), Task 2 (param), Task 4 (Select). ✓
- Status filter → Task 1 (`status.in_`), Task 2 (repeated `status`), Task 4 (multi-select). ✓
- Time-range on `ended_at` → Task 1, Task 2, Task 4 (RangePicker). ✓
- `source="prompt"` added → Task 1 (`_pick_source`), Task 3 (TS union), Task 4 (tag). ✓
- URL-synced controls → Task 4 (`patch`). ✓
- Backward compatible (defaults unchanged) → Task 1 signature defaults; pre-existing tests still pass. ✓
- Testing (fields/status/time/source backend; endpoint; buildSearchParams; page restore + Prompt tag) → each task + Task 5. ✓

**2. Placeholder scan:** No TBD/TODO. `_pick_source`'s `import json as _json` inside the function is intentional (avoids relying on the module-level `json` name shadowing in a copied snippet — it's the same stdlib module, harmless; the module already imports `json` at top so `_pick_source` could use that directly — either works, keep it simple with the top-level `json`). **Implementer note:** `samples.py` already imports `json` at module top, so in `_pick_source` use `json.loads(...)` directly and drop the local `import json as _json`.

**3. Type consistency:** `search_samples_by_response(q, target_profile=None, *, fields, status, created_after, created_before, limit, offset)` matches Task 1 def + Task 2 call. `_match_columns(fields)`/`_pick_source(row, q, fields)` consistent within Task 1. `buildSearchParams(SampleSearchParams)` keys (`q/limit/offset/target_profile/fields/status/created_after/created_before`) match the endpoint's param names (Task 2) and the TS `SampleSearchParams` (Task 3). `SampleSearchHit.source` union (`prompt|response|llm_response`) consistent Task 1 (backend value) ↔ Task 3 (TS). ResponseSearch reads URL keys `fields`/`status`/`created_after`/`created_before` and passes `fields`/`status`/`createdAfter`/`createdBefore` into `useSampleSearch` (Task 4) matching Task 3's param names.
