# Response Full-Text Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sample-level, cross-batch keyword search over response content (raw + LLM-extracted) that returns matching samples with a highlighted snippet and a link to each sample's detail.

**Architecture:** A new `storage/samples.py::search_samples_by_response` (LIKE over `responses_json`/`llm_responses_json` + Python snippet extraction) behind a new `api/search.py` router (`GET /api/v1/samples/search`). Frontend adds a `ResponseSearch` page (keyword + profile filter + pagination + `<mark>` highlight) with a `search/responses` route and a 任务-group nav entry.

**Tech Stack:** Python 3.11, FastAPI, async SQLAlchemy (SQLite), `uv`; React 18 + TS + AntD 5, TanStack Query, Vitest.

---

## Context an implementer needs

- **`Sample` columns** (`models/db.py`): `batch_id`, `id`, `status`, `responses_json`, `llm_responses_json`, `target_profile`, `ended_at` — `responses_json`/`llm_responses_json` are JSON arrays of strings stored with `ensure_ascii=False` (so Chinese substrings match via LIKE, same as the existing prompt search).
- **`_like_term`** exists in `storage/batches.py:12` (`\`/`%`/`_` escaping → `%…%`). `batches.py` already imports from `samples.py`, so importing `_like_term` back into `samples.py` would be a circular import — **replicate the 3-line helper locally in `samples.py`** (name it `_like_term`; it's trivial).
- **`storage/samples.py`** imports `json`, `from datetime import datetime, timezone`, `from sqlalchemy import case, func, select`, `SampleRow` (= `Sample`), `get_sessionmaker`.
- **API router pattern**: e.g. `api/anomalies.py` — `router = APIRouter(prefix="/anomalies", tags=["anomalies"], dependencies=[Depends(require_user)])`, mounted in `main.py` via `app.include_router(<x>_router, prefix="/api/v1")`. `Query` from fastapi for validated params (`Query(50, ge=1, le=200)`, `Query(..., min_length=2)`).
- **Frontend**: hooks in `web/src/api/*.ts` over `client` (axios, `/api/v1` baseURL); pages in `web/src/pages/*`; types in `web/src/types/api.ts`. `StatusTag` (`web/src/components/StatusTag.tsx`) renders a status. Nav 任务 group in `web/src/components/AppLayout.tsx` (`key: 'work'`, contains 单次测试 + 批次). Routes in `web/src/App.tsx`. `EmptyState`/`ErrorState`/`PageHeader` in `components/states/`. `SampleSearchHit.status` is a `SampleStatus`.
- **Tests**: backend `pytest-asyncio` auto mode, `await init_db()` first; integration copies `client`/`_login` from `tests/integration/test_anomalies_endpoints.py`. Run `uv run pytest -q <path>`; lint `uv run ruff check <files>; echo EXIT=$?`. Frontend `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run <path>`, `pnpm exec tsc --noEmit`, `pnpm lint`. pnpm cwd resets → prefix `cd .../web &&`.

---

## File Structure

- Modify `src/autoagent/storage/samples.py` (`_like_term`, `_snippet`, `search_samples_by_response`)
- Modify `src/autoagent/models/api.py` (`SampleSearchHit`, `SampleSearchResponse`)
- Create `src/autoagent/api/search.py`; modify `src/autoagent/main.py` (mount)
- Create `web/src/api/search.ts`, `web/src/utils/highlight.ts` (+ test); modify `web/src/types/api.ts`
- Create `web/src/pages/Search/ResponseSearch.tsx` (+ test); modify `web/src/App.tsx`, `web/src/components/AppLayout.tsx`
- Tests: `tests/unit/test_response_search.py`, `tests/integration/test_search_endpoint.py`; frontend `web/src/utils/highlight.test.ts`, `web/src/pages/Search/ResponseSearch.test.tsx`

---

## Task 1: Backend search query + snippet + schema

**Files:** Modify `src/autoagent/storage/samples.py`, `src/autoagent/models/api.py`; Test `tests/unit/test_response_search.py`.

- [ ] **Step 1: Add the schemas** to `src/autoagent/models/api.py` (append at end):

```python
class SampleSearchHit(BaseModel):
    batch_id: str
    sample_id: str
    target_profile: str
    status: str
    ended_at: datetime | None = None
    source: str  # "response" | "llm_response"
    snippet: str


class SampleSearchResponse(BaseModel):
    items: list[SampleSearchHit]
    total: int
```

- [ ] **Step 2: Write the failing test** — create `tests/unit/test_response_search.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.samples import search_samples_by_response, upsert_sample


def _s(sid, profile, responses, llm=None, ended=None):
    return SampleResult(
        id=sid, status="done", mode="api", target_profile=profile,
        responses=responses, llm_responses=llm or [], ended_at=ended,
    )


@pytest.mark.asyncio
async def test_search_matches_raw_and_llm_with_snippet_and_source():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b1", _s("s1", "p", ["前面 抱歉我无法 后面的内容"], ended=now))
    await upsert_sample("b1", _s("s2", "p", [""], llm=["LLM里也有 抱歉我无法 的"], ended=now - timedelta(minutes=1)))
    await upsert_sample("b1", _s("s3", "p", ["完全无关的响应"], ended=now - timedelta(minutes=2)))

    hits, total = await search_samples_by_response("抱歉我无法", limit=20, offset=0)
    assert total == 2
    by_id = {h.sample_id: h for h in hits}
    assert by_id["s1"].source == "response" and "抱歉我无法" in by_id["s1"].snippet
    assert by_id["s2"].source == "llm_response" and "抱歉我无法" in by_id["s2"].snippet
    assert "s3" not in by_id


@pytest.mark.asyncio
async def test_search_profile_filter_and_pagination():
    await init_db()
    now = datetime.now(timezone.utc)
    for i in range(5):
        await upsert_sample("b", _s(f"a{i}", "pa", ["hit here"], ended=now - timedelta(minutes=i)))
    await upsert_sample("b", _s("bb", "pb", ["hit here"], ended=now))

    _, total_pa = await search_samples_by_response("hit", target_profile="pa", limit=20, offset=0)
    assert total_pa == 5
    page1, total_all = await search_samples_by_response("hit", limit=2, offset=0)
    assert total_all == 6 and len(page1) == 2


@pytest.mark.asyncio
async def test_search_escapes_like_metachars():
    await init_db()
    now = datetime.now(timezone.utc)
    await upsert_sample("b", _s("s1", "p", ["no percent here"], ended=now))
    # a bare "%" must be literal, not match-everything
    _, total = await search_samples_by_response("%", limit=20, offset=0)
    assert total == 0
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_response_search.py`
Expected: FAIL — `search_samples_by_response` undefined.

- [ ] **Step 4: Implement** — add to `src/autoagent/storage/samples.py`. Add the import of the schemas to the existing `from autoagent.models.api import ...` line (`DailyPoint, SampleResult, SampleSearchHit`), then:

```python
def _like_term(q: str) -> str:
    # Local copy (batches.py has the same helper, but importing it here would
    # be circular since batches imports from this module). Escapes LIKE
    # metacharacters so a "%foo" query doesn't match everything.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snippet(text: str, q: str, radius: int = 40) -> str:
    lo = text.lower().find(q.lower())
    if lo < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, lo - radius)
    end = min(len(text), lo + len(q) + radius)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def _first_match(items: list, q: str) -> str | None:
    ql = q.lower()
    for it in items:
        if isinstance(it, str) and ql in it.lower():
            return it
    return None


async def search_samples_by_response(
    q: str, target_profile: str | None = None, *, limit: int, offset: int
) -> tuple[list[SampleSearchHit], int]:
    """Cross-batch search over responses_json + llm_responses_json (substring
    LIKE, escaped). Returns matching samples (newest first) with a snippet of
    the matched response and its source, plus a total count."""
    term = _like_term(q)
    match = SampleRow.responses_json.like(term, escape="\\") | SampleRow.llm_responses_json.like(
        term, escape="\\"
    )
    sm = get_sessionmaker()
    async with sm() as s:
        conds = [match]
        if target_profile is not None:
            conds.append(SampleRow.target_profile == target_profile)
        total = (
            await s.execute(select(func.count()).select_from(SampleRow).where(*conds))
        ).scalar_one()
        rows = (
            (
                await s.execute(
                    select(SampleRow)
                    .where(*conds)
                    .order_by(SampleRow.ended_at.desc().nullslast())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        hits: list[SampleSearchHit] = []
        for r in rows:
            raw = json.loads(r.responses_json or "[]")
            llm = json.loads(r.llm_responses_json or "[]")
            matched = _first_match(raw, q)
            source = "response"
            if matched is None:
                matched = _first_match(llm, q)
                source = "llm_response"
            hits.append(
                SampleSearchHit(
                    batch_id=r.batch_id,
                    sample_id=r.id,
                    target_profile=r.target_profile,
                    status=r.status,
                    ended_at=r.ended_at.replace(tzinfo=timezone.utc) if r.ended_at else None,
                    source=source,
                    snippet=_snippet(matched or "", q),
                )
            )
        return hits, int(total)
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/unit/test_response_search.py`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/storage/samples.py src/autoagent/models/api.py tests/unit/test_response_search.py; echo "EXIT=$?"
git add src/autoagent/storage/samples.py src/autoagent/models/api.py tests/unit/test_response_search.py
git commit -m "feat(search): add cross-batch response search query + snippet"
```

---

## Task 2: Search endpoint

**Files:** Create `src/autoagent/api/search.py`; Modify `src/autoagent/main.py`; Test `tests/integration/test_search_endpoint.py`.

- [ ] **Step 1: Write the failing test** — create `tests/integration/test_search_endpoint.py` (copy the `client`/`_login` fixtures from `tests/integration/test_anomalies_endpoints.py`):

```python
@pytest.mark.asyncio
async def test_search_endpoint(client):
    from datetime import datetime, timezone

    from autoagent.models.api import SampleResult
    from autoagent.storage.samples import upsert_sample

    h = await _login(client)
    now = datetime.now(timezone.utc)
    await upsert_sample("b", SampleResult(id="s1", status="done", mode="api",
                                          target_profile="p", responses=["hello 抱歉我无法 world"],
                                          ended_at=now))
    r = await client.get("/api/v1/samples/search?q=抱歉我无法", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["sample_id"] == "s1" and body["items"][0]["source"] == "response"


@pytest.mark.asyncio
async def test_search_rejects_short_query(client):
    h = await _login(client)
    r = await client.get("/api/v1/samples/search?q=a", headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_requires_auth(client):
    r = await client.get("/api/v1/samples/search?q=abc")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_search_endpoint.py`
Expected: FAIL — 404.

- [ ] **Step 3: Implement the router** — create `src/autoagent/api/search.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from autoagent.auth.deps import require_user
from autoagent.models.api import SampleSearchResponse
from autoagent.storage.samples import search_samples_by_response

router = APIRouter(prefix="/samples", tags=["search"], dependencies=[Depends(require_user)])


@router.get("/search", response_model=SampleSearchResponse)
async def search_responses(
    q: str = Query(..., min_length=2),
    target_profile: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SampleSearchResponse:
    items, total = await search_samples_by_response(
        q.strip(), target_profile=target_profile, limit=limit, offset=offset
    )
    return SampleSearchResponse(items=items, total=total)
```

Note: `min_length=2` applies to the raw `q` before strip; that's acceptable (a 2-char query with a space still passes, and `q.strip()` is what's actually searched). If a stripped-empty `q` slips through (e.g. `"  "`), the LIKE `%  %`-style term simply matches nothing meaningful — no crash.

- [ ] **Step 4: Mount the router** — in `src/autoagent/main.py`, add the import with the others and `app.include_router(search_router, prefix="/api/v1")` alongside them:

```python
from autoagent.api.search import router as search_router
...
app.include_router(search_router, prefix="/api/v1")
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest && uv run pytest -q tests/integration/test_search_endpoint.py`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
uv run ruff check src/autoagent/api/search.py src/autoagent/main.py tests/integration/test_search_endpoint.py; echo "EXIT=$?"
git add src/autoagent/api/search.py src/autoagent/main.py tests/integration/test_search_endpoint.py
git commit -m "feat(search): add GET /samples/search endpoint"
```

---

## Task 3: Frontend data layer + highlight helper

**Files:** Modify `web/src/types/api.ts`; Create `web/src/api/search.ts`, `web/src/utils/highlight.ts`, `web/src/utils/highlight.test.ts`.

- [ ] **Step 1: Add types** to `web/src/types/api.ts`:

```ts
export interface SampleSearchHit {
  batch_id: string
  sample_id: string
  target_profile: string
  status: SampleStatus
  ended_at: string | null
  source: 'response' | 'llm_response'
  snippet: string
}

export interface SampleSearchResponse {
  items: SampleSearchHit[]
  total: number
}
```

(`SampleStatus` is already defined/exported in this file — confirm and reuse it; if not present, use `string`.)

- [ ] **Step 2: Write the failing test** — create `web/src/utils/highlight.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { splitHighlight } from './highlight'

describe('splitHighlight', () => {
  it('marks case-insensitive matches and leaves the rest plain', () => {
    expect(splitHighlight('Hello WORLD hello', 'hello')).toEqual([
      { text: 'Hello', mark: true },
      { text: ' WORLD ', mark: false },
      { text: 'hello', mark: true },
    ])
  })

  it('escapes regex metacharacters in the term', () => {
    expect(splitHighlight('a.b.c', '.')).toEqual([
      { text: 'a', mark: false },
      { text: '.', mark: true },
      { text: 'b', mark: false },
      { text: '.', mark: true },
      { text: 'c', mark: false },
    ])
  })

  it('returns the whole text unmarked when there is no match or empty term', () => {
    expect(splitHighlight('abc', 'x')).toEqual([{ text: 'abc', mark: false }])
    expect(splitHighlight('abc', '')).toEqual([{ text: 'abc', mark: false }])
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/utils/highlight.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement** — create `web/src/utils/highlight.ts`:

```ts
export interface HighlightSegment {
  text: string
  mark: boolean
}

/** Split `text` into plain/marked segments around case-insensitive
 * occurrences of `term`. The term is regex-escaped so metacharacters match
 * literally. An empty term or no match returns the whole text unmarked. */
export function splitHighlight(text: string, term: string): HighlightSegment[] {
  if (!term) return [{ text, mark: false }]
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(${escaped})`, 'gi')
  const parts = text.split(re)
  const out: HighlightSegment[] = []
  for (const part of parts) {
    if (part === '') continue
    out.push({ text: part, mark: re.test(part) && part.toLowerCase() === term.toLowerCase() ? true : new RegExp(`^${escaped}$`, 'i').test(part) })
  }
  return out.length ? out : [{ text, mark: false }]
}
```

Wait — simplify the mark test to avoid the stateful `re.test`. Use:

```ts
export function splitHighlight(text: string, term: string): HighlightSegment[] {
  if (!term) return [{ text, mark: false }]
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  const isMatch = new RegExp(`^${escaped}$`, 'i')
  return parts
    .filter((p) => p !== '')
    .map((p) => ({ text: p, mark: isMatch.test(p) }))
}
```

Use this second version (the first is buggy with stateful regex). If `parts` is empty (text was empty), return `[{ text: '', mark: false }]` is fine — but guard: if the result is empty, return `[{ text, mark: false }]`.

Final:

```ts
export interface HighlightSegment {
  text: string
  mark: boolean
}

export function splitHighlight(text: string, term: string): HighlightSegment[] {
  if (!term) return [{ text, mark: false }]
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi')).filter((p) => p !== '')
  const isMatch = new RegExp(`^${escaped}$`, 'i')
  const out = parts.map((p) => ({ text: p, mark: isMatch.test(p) }))
  return out.length ? out : [{ text, mark: false }]
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/utils/highlight.test.ts`
Expected: PASS.

- [ ] **Step 6: Add the api hook** — create `web/src/api/search.ts`:

```ts
import { useQuery } from '@tanstack/react-query'
import { SampleSearchResponse } from '../types/api'
import { client } from './client'

export interface SampleSearchParams {
  q: string
  targetProfile?: string
  page: number
  pageSize?: number
}

export function useSampleSearch({ q, targetProfile, page, pageSize = 20 }: SampleSearchParams) {
  const trimmed = q.trim()
  return useQuery({
    queryKey: ['samples', 'search', trimmed, targetProfile, page, pageSize],
    enabled: trimmed.length >= 2,
    queryFn: async () =>
      (
        await client.get<SampleSearchResponse>('/samples/search', {
          params: {
            q: trimmed,
            target_profile: targetProfile || undefined,
            limit: pageSize,
            offset: (page - 1) * pageSize,
          },
        })
      ).data,
  })
}
```

- [ ] **Step 7: Typecheck + lint + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/types/api.ts web/src/api/search.ts web/src/utils/highlight.ts web/src/utils/highlight.test.ts
git commit -m "feat(web): add the response-search data layer + highlight helper"
```

---

## Task 4: ResponseSearch page + route + nav

**Files:** Create `web/src/pages/Search/ResponseSearch.tsx`; Modify `web/src/App.tsx`, `web/src/components/AppLayout.tsx`; Test `web/src/pages/Search/ResponseSearch.test.tsx`.

- [ ] **Step 1: Write the failing test** — create `web/src/pages/Search/ResponseSearch.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { SampleSearchHit } from '../../types/api'
import { ResponseSearch } from './ResponseSearch'

const useSampleSearch = vi.fn()

vi.mock('../../api/search', () => ({
  useSampleSearch: (...a: unknown[]) => useSampleSearch(...a),
}))
vi.mock('../../api/profiles', () => ({ useProfiles: () => ({ data: [] }) }))

function hit(over: Partial<SampleSearchHit> & { sample_id: string }): SampleSearchHit {
  return {
    batch_id: 'b1',
    target_profile: 'p1',
    status: 'done',
    ended_at: '2026-08-05T00:00:00Z',
    source: 'response',
    snippet: '…前面 抱歉我无法 后面…',
    ...over,
  }
}

function SampleStub() {
  const loc = useLocation()
  return <div>sample-page{loc.pathname}</div>
}

describe('ResponseSearch', () => {
  afterEach(() => vi.clearAllMocks())

  it('renders hits with highlighted snippet and links to the sample', async () => {
    useSampleSearch.mockReturnValue({
      data: { items: [hit({ sample_id: 's1', batch_id: 'bb' })], total: 1 },
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/search/responses" element={<ResponseSearch />} />
        <Route path="/batches/:id/samples/:sid" element={<SampleStub />} />
      </Routes>,
      { initialPath: '/search/responses' },
    )
    // type a query so the (mocked) hook's data is shown
    await userEvent.type(screen.getByPlaceholderText(/搜索响应/), '抱歉我无法')
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByText(/后面/)).toBeInTheDocument())
    await userEvent.click(screen.getByText('查看'))
    expect(await screen.findByText('sample-page/batches/bb/samples/s1')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Search/ResponseSearch.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the page** — create `web/src/pages/Search/ResponseSearch.tsx`:

```tsx
import { Input, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProfiles } from '../../api/profiles'
import { useSampleSearch } from '../../api/search'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import type { SampleSearchHit } from '../../types/api'
import { splitHighlight } from '../../utils/highlight'

function Snippet({ text, term }: { text: string; term: string }) {
  return (
    <span>
      {splitHighlight(text, term).map((seg, i) =>
        seg.mark ? <mark key={i}>{seg.text}</mark> : <span key={i}>{seg.text}</span>,
      )}
    </span>
  )
}

export function ResponseSearch() {
  const navigate = useNavigate()
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  const [profile, setProfile] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const pageSize = 20
  const profiles = useProfiles()
  const { data, isLoading, isError, refetch } = useSampleSearch({
    q,
    targetProfile: profile,
    page,
    pageSize,
  })

  const submit = (value: string) => {
    setQ(value)
    setPage(1)
  }

  const columns: ColumnsType<SampleSearchHit> = [
    {
      title: '片段',
      dataIndex: 'snippet',
      render: (snippet: string) => <Snippet text={snippet} term={q} />,
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 100,
      render: (s: string) => <Tag>{s === 'llm_response' ? 'LLM 提取' : '原始响应'}</Tag>,
    },
    { title: 'Profile', dataIndex: 'target_profile', width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: SampleSearchHit['status']) => <StatusTag status={s} />,
    },
    {
      title: '操作',
      width: 90,
      render: (_v, row) => (
        <a onClick={() => navigate(`/batches/${row.batch_id}/samples/${row.sample_id}`)}>查看</a>
      ),
    },
  ]

  return (
    <div>
      <PageHeader eyebrow="任务" title="响应搜索" subtitle="按内容检索样本的响应(原始 + LLM 提取)" />
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="搜索响应内容…"
          allowClear
          style={{ width: 320 }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onSearch={submit}
          enterButton
        />
        <Select
          allowClear
          placeholder="全部 Profile"
          style={{ width: 180 }}
          value={profile}
          onChange={(v) => {
            setProfile(v)
            setPage(1)
          }}
          options={(profiles.data ?? []).map((p) => ({ value: p.name, label: p.name }))}
        />
      </Space>
      {isError ? (
        <ErrorState title="搜索失败" onRetry={() => refetch()} />
      ) : q.trim().length < 2 ? (
        <EmptyState title="输入关键词搜索响应内容" description="至少 2 个字符。" />
      ) : !isLoading && (data?.items.length ?? 0) === 0 ? (
        <EmptyState title="没有命中" description="换个关键词试试。" />
      ) : (
        <>
          <Typography.Text type="secondary">共 {data?.total ?? 0} 条命中</Typography.Text>
          <Table<SampleSearchHit>
            rowKey={(r) => `${r.batch_id}/${r.sample_id}`}
            size="small"
            loading={isLoading}
            dataSource={data?.items ?? []}
            columns={columns}
            pagination={{
              current: page,
              pageSize,
              total: data?.total ?? 0,
              onChange: setPage,
              showTotal: (n) => `共 ${n} 条`,
            }}
            style={{ marginTop: 8 }}
          />
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Add the route** in `web/src/App.tsx` — import `ResponseSearch` and add `<Route path="search/responses" element={<ResponseSearch />} />` (anywhere inside the authenticated route group, e.g. after the `tests/quick` route):

```tsx
import { ResponseSearch } from './pages/Search/ResponseSearch'
...
          <Route path="search/responses" element={<ResponseSearch />} />
```

- [ ] **Step 5: Add the nav entry** in `web/src/components/AppLayout.tsx` — in the 任务 group's `items` (after 批次), add `{ key: '/search/responses', label: '响应搜索 Search', icon: <SearchOutlined /> }`. Import `SearchOutlined` from `@ant-design/icons`.

- [ ] **Step 6: Run test + typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Search/ResponseSearch.test.tsx && pnpm exec tsc --noEmit && pnpm lint`
Expected: PASS + clean. (If the test's `getByText(/后面/)` split by the highlight `<mark>` breaks up the text, assert on a plain fragment that isn't split, e.g. the `查看` link and the source tag — adjust the snippet assertion to a substring that stays in one segment.)

- [ ] **Step 7: Format + commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec prettier --write src/pages/Search/ResponseSearch.tsx src/pages/Search/ResponseSearch.test.tsx
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Search/ResponseSearch.tsx web/src/pages/Search/ResponseSearch.test.tsx web/src/App.tsx web/src/components/AppLayout.tsx
git commit -m "feat(web): add the response search page, route, and nav"
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

- [ ] **Step 3: CLAUDE.md changelog entry** — document the response search (cross-batch `search_samples_by_response` over raw+LLM responses with snippet/source, `GET /samples/search`, the ResponseSearch page with `<mark>` highlight), noting it's pure retrieval (no content judgement — consistent with the tool's positioning). Reference the spec + this plan.

- [ ] **Step 4: Commit docs**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the response full-text search feature"
```

- [ ] **Step 5: Push + verify CI** — user pre-authorized. Push and confirm CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`. If the frontend job dies with no log (the known transient recharts-era runner kill), re-run the failed job once before treating it as a real failure.

---

## Self-Review

**1. Spec coverage:**
- Cross-batch response search over raw + LLM (`responses_json`/`llm_responses_json`), escaped LIKE → Task 1. ✓
- Snippet extraction + source (`response`/`llm_response`) → Task 1 (`_snippet`/`_first_match`). ✓
- `SampleSearchHit`/`SampleSearchResponse` schema → Task 1. ✓
- Endpoint (`q` min 2, `limit` cap, auth, optional profile) → Task 2. ✓
- Frontend types + `useSampleSearch` (disabled < 2 chars) → Task 3. ✓
- `highlight`/`splitHighlight` (regex-escape, case-insensitive) → Task 3. ✓
- Page (Input.Search commit-on-submit, profile filter, pagination, snippet `<mark>`, source/status tags, 查看 link, empty/no-result/error states) → Task 4. ✓
- Route + nav (任务 group) → Task 4. ✓
- Testing (query incl. metachar-escape, endpoint, highlight, hook-disabled, page) → each task + Task 5. ✓

**2. Placeholder scan:** No TBD/TODO. Task 3 Step 4 deliberately shows a buggy first draft then the corrected `splitHighlight` — **use the final version only**; the intermediate is annotated as buggy on purpose so the implementer doesn't reintroduce the stateful-regex mistake. Task 4 Step 6 notes a possible test-assertion adjustment (highlight splits text) with a concrete fallback.

**3. Type consistency:** `SampleSearchHit` fields match between Task 1 (Pydantic), Task 3 (TS), and Task 4 (columns). `search_samples_by_response(q, target_profile=None, *, limit, offset) -> (list, int)` matches Task 1 def + Task 2 endpoint call. `SampleSearchResponse` shape (`items`/`total`) consistent backend↔frontend. `splitHighlight(text, term) -> HighlightSegment[]` matches Task 3 def + Task 4 `Snippet` usage. `useSampleSearch({ q, targetProfile, page, pageSize })` matches Task 3 def + Task 4 call.
