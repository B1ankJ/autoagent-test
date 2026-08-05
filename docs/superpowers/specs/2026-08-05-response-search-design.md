# Response Full-Text Search — Design

## Problem

The batch list's `q` search only matches prompts (`Sample.prompts_sent_json` LIKE, plus batch name/id). There's no way to find samples by what the product *responded* — e.g. "which samples' responses contained '抱歉我无法'". Since AutoAgent's job is to *obtain* responses (judging their content is left to other platforms), being able to search and locate responses is a natural retrieval need that doesn't change the tool's positioning.

## Goals

- A sample-level, cross-batch search: type a keyword, get the matching **samples** (not just their batches) with a highlighted snippet, source (raw vs LLM-extracted response), profile, batch, status, time, and a link to the sample detail.
- Search both `responses_json` (raw) and `llm_responses_json` (LLM-extracted), since a profile with LLM extraction enabled often has the "real" answer in the LLM field.

## Non-goals (this iteration)

- Searching prompts here (that's the existing batch-list `q`; this feature is response-focused).
- Any judgement of response content (out of scope by the tool's positioning — this only locates).
- Fuzzy/semantic search, ranking by relevance, or a search index (plain substring LIKE is enough at this scale; the batch-list search already uses LIKE).
- Status/time-range filters on the search (keyword + optional profile only this cut).

## Backend

**New storage query** `storage/samples.py::search_samples_by_response(q, target_profile=None, *, limit, offset) -> tuple[list[SampleSearchHit], int]`:
- `WHERE (responses_json LIKE %q% OR llm_responses_json LIKE %q%)`, escaped via the existing `storage/batches.py::_like_term` pattern (reuse or replicate the same escaping — `\`, `%`, `_`). Chinese matches because both columns are stored with `ensure_ascii=False`.
- Optional `AND target_profile = ?`.
- `ORDER BY ended_at DESC` (nulls last), `LIMIT/OFFSET`. Returns rows + a total count (one count query, one page query — same shape as `list_batches`).
- **Snippet extraction (Python)**: for each hit, parse the two JSON arrays, find the first response string that contains `q` (case-insensitive for the containment test), record `source` (`response` if the raw array matched first, else `llm_response`), and cut a context window around the match (~40 chars each side, with `…` ellipses when truncated). If the LIKE matched the JSON structurally but no individual string contains `q` after parse (edge case), fall back to `source="response"` and an empty/whole-first-string snippet.

**Schema** `SampleSearchHit` (`models/api.py`):
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

**Endpoint** — new router `api/search.py` (`prefix="/samples"`, `dependencies=[Depends(require_user)]`), mounted at `/api/v1` in `main.py`:
`GET /api/v1/samples/search?q=&target_profile=&limit=&offset=` — `q` required, `min_length=2` after strip (rejects a whole-table scan on empty/1-char); `limit = Query(50, ge=1, le=200)`; `offset = Query(0, ge=0)`. Returns `SampleSearchResponse`.

## Frontend

- **Nav + route**: a "响应搜索 Search" entry under 任务 (next to 批次), route `search/responses` → `web/src/pages/Search/ResponseSearch.tsx`.
- **Data layer** `web/src/api/search.ts`: `useSampleSearch({ q, targetProfile, page })` (query disabled when `q.trim().length < 2`). Types `SampleSearchHit`/`SampleSearchResponse` in `web/src/types/api.ts`.
- **Page**: a keyword `Input.Search` (triggers on enter/button — the input value is staged locally and only committed to the query on submit, so it doesn't fire per keystroke), an optional profile `Select` filter, and a paginated result list. Empty query → a guiding prompt ("输入关键词搜索响应内容"). No results → EmptyState "没有命中". Error → `ErrorState`.
- **Result row**: the snippet with the matched term wrapped in `<mark>` (case-insensitive highlight of the submitted term, via a small `highlight(text, term)` helper that splits on the term and marks the matches — safe against regex metacharacters by escaping the term), a source `Tag` (原始响应 / LLM 提取), `target_profile`, batch id (mono), a `StatusTag`, the time, and a 查看 link → `/batches/{batch_id}/samples/{sample_id}`.

## Error handling

- `q` shorter than 2 (after trim) → the frontend doesn't request; the backend returns 422 if called directly.
- LIKE special chars in `q` (`%`, `_`, `\`) are escaped so they're literal.
- A hit whose JSON can't be parsed (corrupt) → snippet falls back to a safe empty/truncated string; the row still renders (never 500s the whole search over one bad row).
- Highlight term escaping prevents a `q` like `.*` from breaking the client-side regex.

## Testing

**Backend:**
- `search_samples_by_response`: matches a raw-response substring; matches an LLM-response substring (`source="llm_response"`); no match → empty; `target_profile` filter narrows; pagination (`limit`/`offset` + `total`); snippet contains the keyword with context; LIKE metachar in `q` is treated literally (a `%` query doesn't match everything).
- Endpoint: auth (401/403), `q` too short → 422, `limit` cap → 422, response shape.

**Frontend:**
- `useSampleSearch`: disabled (no request) when `q` under 2 chars; enabled with a valid `q`.
- `highlight(text, term)`: wraps case-insensitive matches in `<mark>`, escapes regex metachars in the term, returns plain text when no match.
- ResponseSearch page: renders hit rows with highlighted snippet + source/status tags; 查看 navigates with the right batch/sample; empty-query guide and no-results states; nav entry present.
