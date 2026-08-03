# Batch Comparison (Diff) View — Design

## Problem

Comparing two batch runs today (e.g. "did rerunning this batch after a profile
change change any responses / get slower?") means opening two Batches Detail
pages in separate tabs and manually reading responses/durations side by side.
There's no aligned, diffed view.

## Goals

- From Batches List, select exactly 2 batches (reusing the existing checkbox
  multi-select already used for bulk enable/disable/delete) and open a compare
  view.
- Align samples by `Sample.id` (stable across rerun/replay, and across
  resubmitting the same JSON batch definition twice — the two natural
  "compare two runs" scenarios).
- Per matched sample: side-by-side duration (with a colored delta) and, on
  expand, a word-level highlighted diff of each side's *effective* response
  (same rule/LLM priority already used everywhere else — see below).
- Samples present in only one of the two batches are called out separately,
  not silently dropped.

## Non-goals (this iteration)

- Comparing more than 2 batches at once.
- Comparing anything beyond the first prompt/response round of a multi-round
  sample — most batches are single-round; multi-round comparison is a real
  follow-up, not built here (see "Data model" below for the exact behavior on
  a multi-round sample).
- Any backend change — both batches' full data are fetched via the existing
  `useBatch(id)` hook, same as Batches Detail already does.

## Entry point

Batches List's existing `rowSelection` (`selectedIds` state, already used by
the 批量启用/批量禁用/批量删除 toolbar) gains one more action, shown only when
`selectedIds.length === 2`: a "对比" button navigating to
`/batches/compare?a=<id1>&b=<id2>`.

## Data model

Both batches are fetched with the existing `useBatch(id)` hook (one call per
id, in parallel — no new endpoint). Once both have loaded:

```ts
interface SampleComparisonRow {
  sampleId: string
  a: { durationMs?: number; effectiveResponse: string } | null // null = missing from this batch
  b: { durationMs?: number; effectiveResponse: string } | null
}
```

- `effectiveResponse` uses the existing `selectEffectiveResponseText` (from
  `web/src/utils/llmExtraction.ts`) — the same rule/LLM-priority logic already
  used by `ResponseComparison`/`SampleDetail`, so this view can't drift from
  what every other "what response did this sample actually produce" surface
  in the app already shows (this exact class of drift has bitten this
  codebase three times before per existing history — reusing the helper
  avoids a fourth).
- Only the first prompt round is compared: `responses?.[0]` /
  `llm_responses?.[0]` / `llm_errors?.[0]` feed `selectEffectiveResponseText`,
  matching the shape `ResponseComparison` already takes for one round.
- Rows are every sample id present in *either* batch's sample list, sorted by
  id. A row where the id only exists in one batch has `a` or `b` as `null` —
  rendered as a distinct "仅 A 存在" / "仅 B 存在" state, not diffed.
- Matched-row ordering: natural sample id order (not "most different first")
  — keeps the view predictable and matches how Batches Detail's own sample
  table is already ordered.

## Diff computation

New dependency: [`diff`](https://www.npmjs.com/package/diff) (jsdiff, ~20KB
gzipped, the standard/most widely used JS text-diff library) — implementing
Myers diff correctly by hand is exactly the kind of thing worth not
reinventing. Use `diffWords(effectiveA, effectiveB)` for word-level
highlighting (added spans green, removed spans red with strikethrough,
unchanged plain text) — one call per expanded row, computed lazily (only when
a row is actually expanded, not for all rows up front) since a batch can have
many samples and most won't be inspected.

## Component & page

**`web/src/pages/Batches/Compare.tsx`** (new route, added to the router
alongside the other `/batches/*` routes):

- Reads `a`/`b` from the query string, calls `useBatch(a)` and `useBatch(b)`.
- Loading/error states: reuse the existing `PageSkeleton`/`ErrorState`
  patterns already used by Batches Detail, gated on either query still
  loading / erroring.
- Header: both batches' names + a link back to each one's own detail page.
- An AntD `Table<SampleComparisonRow>` with `expandable`:
  - Collapsed row: sample id, 耗时 A, 耗时 B, Δ (colored red when B is slower
    than A, green when faster — a directional convention specific to this
    delta column, distinct from Batches List's duration-anomaly highlight,
    which is a magnitude-only red regardless of direction), and a status
    badge for the "仅 A/B 存在" case instead of the duration columns.
  - Expanded row (only for matched samples): the `diffWords` output rendered
    as inline highlighted spans, computed via `useMemo` scoped to that row so
    collapsing/re-expanding doesn't recompute.
- A summary line above the table: "N 个共同 sample · M 个仅 A · K 个仅 B".

## Error handling

- Either batch failing to load: show that batch's own error (reusing
  `ErrorState`) instead of a blank/broken compare view — the other batch's
  data isn't discarded, just nothing to compare it against yet.
- Zero samples in common: table renders empty with an `EmptyState` message
  ("这两个批次没有共同的 sample id"), the "仅 A/仅 B" summary numbers still
  shown above it so the page isn't just a dead end.

## Testing

- Unit test the row-building logic (matching/sorting/effective-response
  selection) in isolation as a pure function, separate from the page
  component — same pattern as `buildTimelineEvents`/`groupFailuresByError`
  before it.
- Component test for the Compare page: two mocked `useBatch` results, verify
  matched/unmatched row counts and labels, expanding a row shows diff output,
  a sample missing from one side shows the right badge instead of a diff.
- Batches List test: 对比 button only appears at exactly 2 selected, clicking
  it navigates to the right query string.
