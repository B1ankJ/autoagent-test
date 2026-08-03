# Failure Reason Clustering — Design

## Problem

Debugging a batch with many failed samples today means reading each failed
sample's `error` text one by one — there's no way to see "these 12 failures are
all the same root cause" at a glance. Batches Detail already has an `error`
column and a free-text search over it, but no grouping/counting.

## Goals

- On Batches Detail, show a collapsible panel above the sample table listing
  failed samples grouped by *normalized* error text, sorted by count descending
  (each group: the normalized pattern, its count, one full example error).
- Clicking a group filters the sample table down to that group's samples,
  composing (AND) with the existing status filter and free-text search rather
  than replacing them.
- Pure frontend. No backend change — `Batch.samples` (with each sample's `error`)
  is already fully loaded by Batches Detail via `useBatchStream`.

## Non-goals (this iteration)

- Cross-batch clustering (grouping failures across multiple batches/over time).
  Scoped to one batch's own samples for now — a natural follow-up once this
  proves useful.
- Any ML/fuzzy-similarity approach (embeddings, edit-distance thresholds). See
  "Clustering approach" below for why.
- Clustering on anything other than `error` text (e.g. response content).

## Clustering approach

`error` is `str(exception)` — free text that routinely embeds run-specific
values (device serial, timeout milliseconds, tap coordinates, session/batch
ids, timestamps) alongside the actually-meaningful part of the message. Two
failures with the *same root cause* often don't share an identical string
because of these embedded variables (e.g. `"device offline: emulator-5554"` vs
`"device offline: emulator-5556"`).

Approach: **regex normalization, then exact match** — replace known
variable-shaped substrings with placeholder tokens, then group by the
resulting normalized string exactly (no fuzzy threshold to tune, no new
dependency, fully deterministic and explainable — the normalized string *is*
the reason a click grouped two errors together).

Normalization rules (applied in this order; each independent, non-overlapping
pattern):

| Pattern | Example | Replaced with |
|---|---|---|
| `\d+(\.\d+)?\s*ms\b` | `30000ms` | `<MS>ms` |
| `\d+(\.\d+)?\s*s\b` (not preceded by a letter, to avoid matching inside words) | `5.2s` | `<N>s` |
| `\(\s*-?\d+\s*,\s*-?\d+\s*\)` | `(495, 2059)` | `(<X>, <Y>)` |
| `\bemulator-\d+\b` | `emulator-5554` | `<DEVICE>` |
| `\b[0-9a-fA-F]{6,}\b` | a hex device serial or hash | `<ID>` |
| ISO-ish timestamp `\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*` | `2026-08-03T00:00:00Z` | `<TIMESTAMP>` |

Deliberately **not** touched: quoted content (locator/selector strings inside
`'...'`/`"..."`) and plain small integers with no surrounding unit — collapsing
`"element not found: '#send-button'"` and `"element not found: '#input'"`
together would hide that these are two different missing elements, which is
exactly the kind of distinction a human scanning failures needs to keep. This
rule set only covers patterns actually observed in this codebase's `error=`
call sites (`batch_scheduler.py`, executor modules); it's a starting point, not
exhaustive — false negatives (same root cause not merged) are an acceptable,
correctable-later trade-off; false positives (different root causes wrongly
merged) are the one we're actively avoiding by keeping rules narrow.

## Data flow

Pure function, one file:

```ts
interface FailureCluster {
  pattern: string       // normalized error text
  count: number
  sampleIds: string[]
  example: string        // one full (non-normalized) error string from the group
}

function groupFailuresByError(samples: Sample[]): FailureCluster[]
```

Input: the same `allSamples` array Batches Detail already computes from
`data.samples`. Only samples with `status === 'failed'` and a non-empty `error`
contribute. Output sorted by `count` descending, ties broken by first
appearance order (stable sort).

## Component

**`FailureClusterPanel`** (new), rendered on Batches Detail above the existing
sample `<Table>`:

- Props: `samples: Sample[]`, `activeClusterId: string | null`, `onSelectCluster: (id: string | null) => void`.
- Computes `groupFailuresByError(samples)` via `useMemo`.
- Renders nothing (returns `null`) when fewer than 2 failed samples exist —
  with 0 or 1 failures there's nothing worth grouping, and an always-visible
  empty/single-item panel would just be noise on every non-trivial batch.
- Otherwise: an AntD `Collapse` (collapsed by default, so it doesn't push the
  sample table down for people who don't care), one row per cluster inside:
  count badge, the normalized pattern (monospace), the example error text
  (`Typography.Paragraph` with `ellipsis={{ rows: 2, expandable: true }}`), and
  a "筛选" / "取消筛选" toggle button that calls `onSelectCluster`.

**Batches Detail integration:** new `activeClusterId` state (`string | null`,
keyed by the cluster's `pattern` — stable and unique per render since it comes
from the same `groupFailuresByError` output). `filteredSamples`'s existing
`useMemo` gains one more condition, ANDed with the current `filter`/`search`
checks: if `activeClusterId` is set, only keep samples whose `id` is in that
cluster's `sampleIds`. Selecting a different cluster (or the same one again,
toggling off) replaces/clears `activeClusterId` — only one cluster filter
active at a time, consistent with there being one filter row already for
status.

## Error handling

None needed beyond what's already there — this reads data Batches Detail
already has loaded and handled (loading/error states for the whole page
already exist upstream of this panel).

## Testing

- Unit test `groupFailuresByError` in isolation: empty input, no failed
  samples, one cluster from several matching-after-normalization errors,
  multiple distinct clusters, a `null`/empty `error` sample excluded, sort
  order (highest count first).
- Unit test each normalization rule with a small table-driven test (one input
  string per rule, assert the normalized output).
- Component test for `FailureClusterPanel`: renders nothing under 2 failures,
  renders one row per cluster with the right count above threshold, clicking
  "筛选" calls `onSelectCluster` with the right id, clicking it again (already
  active) calls it with `null`.
- Component/integration test on Batches Detail: selecting a cluster narrows
  the visible table rows to that cluster's `sampleIds`, combined with an
  already-active status filter (both conditions apply).
