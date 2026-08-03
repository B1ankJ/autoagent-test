# Batch Comparison (Diff) View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user pick exactly two batches from Batches List and open a side-by-side view that aligns samples by `Sample.id`, shows a duration delta per sample, and renders a word-level text diff of each side's effective response on expand.

**Architecture:** Pure frontend, no backend change. A pure function (`buildBatchComparison`) aligns the two batches' sample arrays by id and computes each side's effective response (reusing the existing `selectEffectiveResponseText` so this view can't drift from every other "what response did this sample actually produce" surface). A small `DiffText` component renders `diffWords` output from the new `diff` (jsdiff) dependency. A new `Compare.tsx` page fetches both batches via the existing `useBatch` hook and renders an AntD `Table` with expandable rows. Batches List's existing checkbox selection gains a "对比" action shown only when exactly 2 are selected.

**Tech Stack:** React 18 + TypeScript, AntD 5, TanStack Query v5, `diff` (jsdiff) for word-level diffing, Vitest + React Testing Library.

---

## Context an implementer needs

- **`selectEffectiveResponseText`** lives in `web/src/utils/llmExtraction.ts`:
  ```ts
  export function selectEffectiveResponseText({
    ruleResponse,   // string | undefined
    llmResponse,    // string | null | undefined
    llmError,       // string | null | undefined
    llmEnabled,     // boolean
  }): string
  ```
  and `hasLLMExtractionData(llmResponses?, llmErrors?)` returns whether LLM extraction data exists. `BatchPromptModal.tsx` already uses both exactly this way — LLM wins only when enabled, no error, and non-empty text; otherwise the raw rule response.

- **Types** (`web/src/types/api.ts`): `Sample` has `id: string`, `responses?: string[]`, `llm_responses?: string[]`, `llm_errors?: Array<string | null>`, `duration_ms?: number`. `BatchDetail extends BatchSummary` and has `samples: Sample[]`, `name: string`, `batch_id: string`, `status: BatchStatus`.

- **`useBatch(id: string | undefined)`** (`web/src/api/batches.ts`) returns a TanStack Query result of `BatchDetail`; `enabled: !!id`; polls every 2s while `running`/`queued`.

- **Shared state components** (`web/src/components/states/`): `PageHeader`, `PageSkeleton`, `ErrorState` (props `title`/`description`/`detail`/`onRetry`), `EmptyState` (props `title`/`description`/`action`).

- **Test harness**: `renderWithProviders(ui, { initialPath })` from `web/src/test/test-utils.tsx` wraps in `QueryClientProvider` + AntD `ConfigProvider`/`App` + `MemoryRouter`. Prior pure-function tests: `web/src/utils/failureClustering.test.ts`. Prior page/component tests: `web/src/pages/Batches/Detail.test.tsx`, `web/src/components/FailureClusterPanel.test.tsx`.

- **AntD 2-char CJK button labels** auto-insert a space between the two characters, so RTL button queries must use a regex like `/对\s?比/`, not exact-string equality.

- **Commands** (run from `web/`):
  - Single test file: `pnpm test -- --run src/utils/batchComparison.test.ts`
  - Typecheck: `pnpm exec tsc --noEmit`
  - Lint: `pnpm lint`
  - Build: `pnpm build`
  - If pnpm errors with `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND`, prefix with `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web &&` — the shell cwd can reset between calls.

---

## File Structure

- **Create** `web/src/utils/batchComparison.ts` — pure alignment logic: `buildBatchComparison(samplesA, samplesB)` → `{ rows, commonCount, onlyACount, onlyBCount }`. Depends only on `selectEffectiveResponseText`/`hasLLMExtractionData` and the `Sample` type.
- **Create** `web/src/utils/batchComparison.test.ts` — unit tests for the pure function.
- **Create** `web/src/components/DiffText.tsx` — renders `diffWords(before, after)` as inline highlighted spans (added = success bg, removed = error bg + line-through). Theme-aware via `theme.useToken()`.
- **Create** `web/src/components/DiffText.test.tsx` — component test.
- **Create** `web/src/pages/Batches/Compare.tsx` — the compare page. Reads `a`/`b` from the query string, fetches both via `useBatch`, renders the table + summary + states.
- **Create** `web/src/pages/Batches/Compare.test.tsx` — page component test.
- **Modify** `web/src/App.tsx` — register the `batches/compare` route.
- **Modify** `web/src/pages/Batches/List.tsx` — add the "对比" button to the selection toolbar.
- **Modify** `web/src/pages/Batches/List.test.tsx` — test the button gating + navigation.
- **Modify** `CLAUDE.md` — changelog entry.

---

## Task 1: Pure alignment logic (`buildBatchComparison`)

**Files:**
- Create: `web/src/utils/batchComparison.ts`
- Test: `web/src/utils/batchComparison.test.ts`

- [ ] **Step 1: Write the failing test**

Create `web/src/utils/batchComparison.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildBatchComparison } from './batchComparison'
import type { Sample } from '../types/api'

function sample(overrides: Partial<Sample> & { id: string }): Sample {
  return {
    prompts: ['hi'],
    mode: 'api',
    target_profile: 'p',
    ...overrides,
  }
}

describe('buildBatchComparison', () => {
  it('aligns samples by id, sorted by id, counting common/only-A/only-B', () => {
    const a = [
      sample({ id: 's2', responses: ['A2'], duration_ms: 100 }),
      sample({ id: 's1', responses: ['A1'], duration_ms: 200 }),
      sample({ id: 'only-a', responses: ['x'], duration_ms: 50 }),
    ]
    const b = [
      sample({ id: 's1', responses: ['B1'], duration_ms: 220 }),
      sample({ id: 's2', responses: ['A2'], duration_ms: 90 }),
      sample({ id: 'only-b', responses: ['y'], duration_ms: 60 }),
    ]

    const result = buildBatchComparison(a, b)

    expect(result.rows.map((r) => r.sampleId)).toEqual([
      'only-a',
      'only-b',
      's1',
      's2',
    ])
    expect(result.commonCount).toBe(2)
    expect(result.onlyACount).toBe(1)
    expect(result.onlyBCount).toBe(1)

    const s1 = result.rows.find((r) => r.sampleId === 's1')!
    expect(s1.a).toEqual({ durationMs: 200, effectiveResponse: 'A1' })
    expect(s1.b).toEqual({ durationMs: 220, effectiveResponse: 'B1' })

    const onlyA = result.rows.find((r) => r.sampleId === 'only-a')!
    expect(onlyA.a).not.toBeNull()
    expect(onlyA.b).toBeNull()

    const onlyB = result.rows.find((r) => r.sampleId === 'only-b')!
    expect(onlyB.a).toBeNull()
    expect(onlyB.b).not.toBeNull()
  })

  it('uses the LLM-reviewed response as effective when LLM extraction succeeded', () => {
    const a = [
      sample({
        id: 's1',
        responses: ['raw'],
        llm_responses: ['reviewed'],
        llm_errors: [null],
      }),
    ]
    const b = [sample({ id: 's1', responses: ['raw'] })]

    const result = buildBatchComparison(a, b)
    const row = result.rows[0]
    expect(row.a?.effectiveResponse).toBe('reviewed')
    expect(row.b?.effectiveResponse).toBe('raw')
  })

  it('falls back to the raw response when the LLM extraction errored', () => {
    const a = [
      sample({
        id: 's1',
        responses: ['raw'],
        llm_responses: [''],
        llm_errors: ['auth failed'],
      }),
    ]
    const result = buildBatchComparison(a, [])
    expect(result.rows[0].a?.effectiveResponse).toBe('raw')
  })

  it('compares only the first round of a multi-round sample', () => {
    const a = [sample({ id: 's1', responses: ['first', 'second'] })]
    const b = [sample({ id: 's1', responses: ['FIRST', 'SECOND'] })]
    const result = buildBatchComparison(a, b)
    expect(result.rows[0].a?.effectiveResponse).toBe('first')
    expect(result.rows[0].b?.effectiveResponse).toBe('FIRST')
  })

  it('returns empty rows and zero counts for two empty batches', () => {
    const result = buildBatchComparison([], [])
    expect(result.rows).toEqual([])
    expect(result.commonCount).toBe(0)
    expect(result.onlyACount).toBe(0)
    expect(result.onlyBCount).toBe(0)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/utils/batchComparison.test.ts`
Expected: FAIL — `Failed to resolve import './batchComparison'` / `buildBatchComparison is not a function`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/utils/batchComparison.ts`:

```ts
import type { Sample } from '../types/api'
import { hasLLMExtractionData, selectEffectiveResponseText } from './llmExtraction'

/** One side (A or B) of a compared sample: its duration and the single
 * "effective" response (rule vs LLM-reviewed, same priority as everywhere
 * else in the app), for the first prompt round only. */
export interface SampleSide {
  durationMs?: number
  effectiveResponse: string
}

/** One aligned row: a sample id and each batch's side (null = the id is
 * absent from that batch). */
export interface SampleComparisonRow {
  sampleId: string
  a: SampleSide | null
  b: SampleSide | null
}

export interface BatchComparison {
  rows: SampleComparisonRow[]
  commonCount: number
  onlyACount: number
  onlyBCount: number
}

// Only the first prompt round is compared — most batches are single-round,
// and multi-round comparison is an explicit non-goal for this iteration.
function sideOf(sample: Sample): SampleSide {
  const llmEnabled = hasLLMExtractionData(sample.llm_responses, sample.llm_errors)
  const effectiveResponse = selectEffectiveResponseText({
    ruleResponse: sample.responses?.[0],
    llmResponse: sample.llm_responses?.[0],
    llmError: sample.llm_errors?.[0],
    llmEnabled,
  })
  return { durationMs: sample.duration_ms, effectiveResponse }
}

/** Aligns two batches' sample arrays by `Sample.id`. Rows cover every id
 * present in either batch, sorted by id. A row where the id exists in only
 * one batch has the missing side as `null`. */
export function buildBatchComparison(
  samplesA: Sample[],
  samplesB: Sample[],
): BatchComparison {
  const mapA = new Map(samplesA.map((s) => [s.id, s]))
  const mapB = new Map(samplesB.map((s) => [s.id, s]))
  const allIds = Array.from(new Set([...mapA.keys(), ...mapB.keys()])).sort()

  let commonCount = 0
  let onlyACount = 0
  let onlyBCount = 0

  const rows: SampleComparisonRow[] = allIds.map((id) => {
    const sa = mapA.get(id)
    const sb = mapB.get(id)
    if (sa && sb) commonCount++
    else if (sa) onlyACount++
    else onlyBCount++
    return {
      sampleId: id,
      a: sa ? sideOf(sa) : null,
      b: sb ? sideOf(sb) : null,
    }
  })

  return { rows, commonCount, onlyACount, onlyBCount }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/utils/batchComparison.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/utils/batchComparison.ts web/src/utils/batchComparison.test.ts
git commit -m "feat(web): add batch comparison row-building logic"
```

---

## Task 2: `DiffText` component (jsdiff dependency)

**Files:**
- Modify: `web/package.json` (via `pnpm add`)
- Create: `web/src/components/DiffText.tsx`
- Test: `web/src/components/DiffText.test.tsx`

- [ ] **Step 1: Add the `diff` dependency**

Run:
```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm add diff@^5.2.0 && pnpm add -D @types/diff@^5.2.0
```
Expected: `web/package.json` gains `"diff": "^5.2.0"` under dependencies and `"@types/diff": "^5.2.0"` under devDependencies; `pnpm-lock.yaml` updates.

- [ ] **Step 2: Write the failing test**

Create `web/src/components/DiffText.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { DiffText } from './DiffText'

describe('DiffText', () => {
  it('renders unchanged, removed (strikethrough) and added words', () => {
    renderWithProviders(<DiffText before="hello world" after="hello there" />)

    // Unchanged text stays present.
    expect(screen.getByText(/hello/)).toBeInTheDocument()

    // The word only in `before` is marked removed with a line-through.
    const removed = screen.getByText('world')
    expect(removed).toHaveStyle({ textDecoration: 'line-through' })

    // The word only in `after` is present (added).
    expect(screen.getByText('there')).toBeInTheDocument()
  })

  it('renders identical strings with no removed/added marks', () => {
    const { container } = renderWithProviders(
      <DiffText before="same text" after="same text" />,
    )
    expect(container.textContent).toContain('same text')
    expect(
      container.querySelector('[style*="line-through"]'),
    ).toBeNull()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/components/DiffText.test.tsx`
Expected: FAIL — `Failed to resolve import './DiffText'`.

- [ ] **Step 4: Write minimal implementation**

Create `web/src/components/DiffText.tsx`:

```tsx
import { theme } from 'antd'
import { diffWords } from 'diff'
import { useMemo } from 'react'

interface Props {
  before: string
  after: string
}

/** Word-level diff of two strings: words only in `before` are shown removed
 * (error background + strikethrough), words only in `after` are shown added
 * (success background), unchanged words are plain. Theme-aware via AntD
 * tokens so it reads correctly in both light and dark mode. Diff is memoized
 * on the input pair so re-renders don't recompute. */
export function DiffText({ before, after }: Props) {
  const { token } = theme.useToken()
  const parts = useMemo(() => diffWords(before, after), [before, after])

  return (
    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.7 }}>
      {parts.map((part, i) => {
        if (part.added) {
          return (
            <span
              key={i}
              style={{ background: token.colorSuccessBg, color: token.colorSuccess }}
            >
              {part.value}
            </span>
          )
        }
        if (part.removed) {
          return (
            <span
              key={i}
              style={{
                background: token.colorErrorBg,
                color: token.colorError,
                textDecoration: 'line-through',
              }}
            >
              {part.value}
            </span>
          )
        }
        return <span key={i}>{part.value}</span>
      })}
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/components/DiffText.test.tsx`
Expected: PASS (2 tests).

Note: if `screen.getByText('world')` fails because jsdiff attached surrounding whitespace to the removed token, switch that query to `screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent?.trim() === 'world')` — but jsdiff's `diffWords` groups unchanged whitespace into the unchanged segment, so `'world'` should be its own token.

- [ ] **Step 6: Typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/package.json web/pnpm-lock.yaml web/src/components/DiffText.tsx web/src/components/DiffText.test.tsx
git commit -m "feat(web): add word-level DiffText component (jsdiff)"
```

---

## Task 3: Compare page + route

**Files:**
- Create: `web/src/pages/Batches/Compare.tsx`
- Test: `web/src/pages/Batches/Compare.test.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/src/pages/Batches/Compare.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { BatchDetail } from '../../types/api'
import { Compare } from './Compare'

const useBatch = vi.fn()

vi.mock('../../api/batches', () => ({
  useBatch: (...args: unknown[]) => useBatch(...args),
}))

function batch(overrides: Partial<BatchDetail>): BatchDetail {
  return {
    batch_id: 'b',
    name: 'Batch',
    mode: 'api',
    status: 'done',
    total: 0,
    done: 0,
    failed: 0,
    concurrency: 1,
    seq: 1,
    samples: [],
    ...overrides,
  }
}

function mockBatches(a: BatchDetail, b: BatchDetail) {
  useBatch.mockImplementation((id: string | undefined) => {
    if (id === a.batch_id) return { data: a, isLoading: false, isError: false, error: null }
    if (id === b.batch_id) return { data: b, isLoading: false, isError: false, error: null }
    return { data: undefined, isLoading: false, isError: false, error: null }
  })
}

function renderCompare(search: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/batches/compare" element={<Compare />} />
    </Routes>,
    { initialPath: `/batches/compare${search}` },
  )
}

describe('Compare', () => {
  afterEach(() => {
    useBatch.mockReset()
  })

  it('shows the summary counts and matched/unmatched rows', async () => {
    mockBatches(
      batch({
        batch_id: 'b1',
        name: 'Run A',
        samples: [
          { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', responses: ['hello world'], duration_ms: 100 },
          { id: 'only-a', prompts: ['x'], mode: 'api', target_profile: 'p', responses: ['x'], duration_ms: 50 },
        ],
      }),
      batch({
        batch_id: 'b2',
        name: 'Run B',
        samples: [
          { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', responses: ['hello there'], duration_ms: 130 },
        ],
      }),
    )

    renderCompare('?a=b1&b=b2')

    await waitFor(() => expect(screen.getByText('Run A')).toBeInTheDocument())
    expect(screen.getByText('Run B')).toBeInTheDocument()
    // Summary: 1 common, 1 only-A, 0 only-B.
    expect(screen.getByText(/1 个共同 sample/)).toBeInTheDocument()
    expect(screen.getByText(/1 个仅 A/)).toBeInTheDocument()
    expect(screen.getByText(/0 个仅 B/)).toBeInTheDocument()

    // Both rows render by id.
    expect(screen.getByText('s1')).toBeInTheDocument()
    expect(screen.getByText('only-a')).toBeInTheDocument()
    // The only-A row is flagged as one-sided.
    expect(screen.getByText('仅 A 存在')).toBeInTheDocument()
  })

  it('shows the word-level diff when a matched row is expanded', async () => {
    mockBatches(
      batch({
        batch_id: 'b1',
        name: 'Run A',
        samples: [
          { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', responses: ['hello world'], duration_ms: 100 },
        ],
      }),
      batch({
        batch_id: 'b2',
        name: 'Run B',
        samples: [
          { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', responses: ['hello there'], duration_ms: 130 },
        ],
      }),
    )

    const { container } = renderCompare('?a=b1&b=b2')
    await waitFor(() => expect(screen.getByText('s1')).toBeInTheDocument())

    const expandIcon = container.querySelector('.ant-table-row-expand-icon')
    expect(expandIcon).not.toBeNull()
    await userEvent.click(expandIcon as HTMLElement)

    await waitFor(() => {
      expect(screen.getByText('world')).toBeInTheDocument()
      expect(screen.getByText('there')).toBeInTheDocument()
    })
  })

  it('shows an error state when a batch fails to load', async () => {
    useBatch.mockImplementation((id: string | undefined) => {
      if (id === 'b1') {
        return { data: undefined, isLoading: false, isError: true, error: new Error('boom') }
      }
      return { data: batch({ batch_id: 'b2', name: 'Run B' }), isLoading: false, isError: false, error: null }
    })

    renderCompare('?a=b1&b=b2')
    await waitFor(() => expect(screen.getByText(/加载失败/)).toBeInTheDocument())
  })

  it('shows an error state when a or b is missing from the query string', async () => {
    useBatch.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null })
    renderCompare('?a=b1')
    expect(await screen.findByText(/需要选择两个批次/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Batches/Compare.test.tsx`
Expected: FAIL — `Failed to resolve import './Compare'`.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/pages/Batches/Compare.tsx`:

```tsx
import { ArrowLeftOutlined } from '@ant-design/icons'
import { Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useBatch } from '../../api/batches'
import { DiffText } from '../../components/DiffText'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { buildBatchComparison, type SampleComparisonRow } from '../../utils/batchComparison'
import { formatDurationMs } from '../../utils/duration'

function DurationCell({ ms }: { ms?: number }) {
  if (ms === undefined) return <span className="aa-mono">-</span>
  return (
    <span className="aa-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
      {formatDurationMs(ms)}
    </span>
  )
}

/** Δ = B − A. Positive (B slower) is rendered danger-red, negative (B
 * faster) success-green — a directional convention specific to this column,
 * distinct from Batches List's magnitude-only anomaly highlight. */
function DeltaCell({ row }: { row: SampleComparisonRow }) {
  if (!row.a || !row.b || row.a.durationMs === undefined || row.b.durationMs === undefined) {
    return <span className="aa-mono">-</span>
  }
  const delta = row.b.durationMs - row.a.durationMs
  if (delta === 0) return <span className="aa-mono">0</span>
  const sign = delta > 0 ? '+' : '-'
  return (
    <Typography.Text
      type={delta > 0 ? 'danger' : 'success'}
      className="aa-mono"
      style={{ fontVariantNumeric: 'tabular-nums' }}
    >
      {sign}
      {formatDurationMs(Math.abs(delta))}
    </Typography.Text>
  )
}

export function Compare() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const aId = params.get('a') ?? undefined
  const bId = params.get('b') ?? undefined

  const aQ = useBatch(aId)
  const bQ = useBatch(bId)

  const comparison = useMemo(() => {
    if (!aQ.data || !bQ.data) return null
    return buildBatchComparison(aQ.data.samples, bQ.data.samples)
  }, [aQ.data, bQ.data])

  const breadcrumb = (
    <a onClick={() => navigate('/batches')} style={{ color: 'var(--aa-text-muted)' }}>
      <ArrowLeftOutlined /> 批次
    </a>
  )

  if (!aId || !bId) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="批次对比" />
        <ErrorState
          title="需要选择两个批次"
          description="请从批次列表勾选恰好两个批次后再点击对比。"
          onRetry={() => navigate('/batches')}
          retryLabel="返回批次列表"
        />
      </div>
    )
  }

  if (aQ.isError || bQ.isError) {
    const err = (aQ.error ?? bQ.error) as Error | undefined
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="批次对比" />
        <ErrorState
          title="批次加载失败"
          description="其中一个批次无法加载,可能已被删除或清理。"
          detail={err?.message}
          onRetry={() => {
            aQ.refetch()
            bQ.refetch()
          }}
        />
      </div>
    )
  }

  if (!aQ.data || !bQ.data || !comparison) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="批次对比" />
        <PageSkeleton rows={6} table />
      </div>
    )
  }

  const columns: ColumnsType<SampleComparisonRow> = [
    {
      title: 'Sample ID',
      dataIndex: 'sampleId',
      key: 'sampleId',
      render: (value: string, row) => (
        <Space size={6}>
          <span className="aa-mono">{value}</span>
          {!row.a ? <Tag color="blue">仅 B 存在</Tag> : null}
          {!row.b ? <Tag color="orange">仅 A 存在</Tag> : null}
        </Space>
      ),
    },
    {
      title: '耗时 A',
      key: 'durationA',
      width: 120,
      render: (_v, row) => <DurationCell ms={row.a?.durationMs} />,
    },
    {
      title: '耗时 B',
      key: 'durationB',
      width: 120,
      render: (_v, row) => <DurationCell ms={row.b?.durationMs} />,
    },
    {
      title: 'Δ',
      key: 'delta',
      width: 120,
      render: (_v, row) => <DeltaCell row={row} />,
    },
  ]

  return (
    <div>
      <PageHeader
        eyebrow={breadcrumb}
        title="批次对比"
        subtitle={
          <Space size={8} wrap>
            <a onClick={() => navigate(`/batches/${aQ.data!.batch_id}`)}>A: {aQ.data.name}</a>
            <span style={{ color: 'var(--aa-text-muted)' }}>vs</span>
            <a onClick={() => navigate(`/batches/${bQ.data!.batch_id}`)}>B: {bQ.data.name}</a>
          </Space>
        }
      />

      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        {comparison.commonCount} 个共同 sample · {comparison.onlyACount} 个仅 A ·{' '}
        {comparison.onlyBCount} 个仅 B
      </Typography.Paragraph>

      <Table<SampleComparisonRow>
        rowKey="sampleId"
        size="small"
        dataSource={comparison.rows}
        columns={columns}
        pagination={false}
        expandable={{
          rowExpandable: (row) => !!row.a && !!row.b,
          expandedRowRender: (row) =>
            row.a && row.b ? (
              <DiffText before={row.a.effectiveResponse} after={row.b.effectiveResponse} />
            ) : null,
        }}
        locale={{ emptyText: '这两个批次没有共同的 sample id' }}
      />
    </div>
  )
}
```

- [ ] **Step 4: Register the route**

In `web/src/App.tsx`, add the import after the other Batches imports (line 8 region):

```tsx
import { Compare as BatchCompare } from './pages/Batches/Compare'
```

Then add the route immediately before the `batches/:id` route (so the static `compare` segment is unambiguous), inside the authenticated route group:

```tsx
          <Route path="batches/new" element={<BatchNew />} />
          <Route path="batches/compare" element={<BatchCompare />} />
          <Route path="batches/:id" element={<BatchDetail />} />
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Batches/Compare.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 6: Typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Batches/Compare.tsx web/src/pages/Batches/Compare.test.tsx web/src/App.tsx
git commit -m "feat(web): add the batch comparison page + route"
```

---

## Task 4: "对比" button in Batches List selection toolbar

**Files:**
- Modify: `web/src/pages/Batches/List.tsx`
- Test: `web/src/pages/Batches/List.test.tsx`

- [ ] **Step 1: Write the failing test**

Add this test to `web/src/pages/Batches/List.test.tsx`. First add the needed imports at the top of the file if not already present — the file already imports `screen`, `userEvent`, `renderWithProviders`, `BatchSummary`, `BatchList`. Add near the other imports:

```tsx
import { Route, Routes, useLocation } from 'react-router-dom'
```

Then add a stub component (place it after the existing top-level `batch` fixture definition):

```tsx
function CompareStub() {
  const location = useLocation()
  return <div>compare-page{location.search}</div>
}

const batch2: BatchSummary = {
  batch_id: 'b2',
  name: 'smoke run',
  mode: 'api',
  status: 'done',
  total: 1,
  done: 1,
  failed: 0,
  started_at: '2026-04-22T00:00:00Z',
  profiles: ['p1'],
  devices: [],
}
```

Then add a new `describe` block at the end of the file:

```tsx
describe('BatchList compare action', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseBatches.mockReturnValue({
      data: [batch, batch2],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockUseBatchStats.mockReturnValue({ data: undefined })
    mockUseSessionConversation.mockReturnValue({ data: undefined })
  })

  it('shows 对比 only when exactly 2 are selected and navigates with a/b', async () => {
    renderWithProviders(
      <Routes>
        <Route path="/batches" element={<BatchList />} />
        <Route path="/batches/compare" element={<CompareStub />} />
      </Routes>,
      { initialPath: '/batches' },
    )

    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    // No selection → no 对比 button.
    expect(screen.queryByRole('button', { name: /对\s?比/ })).not.toBeInTheDocument()

    const checkboxes = screen.getAllByRole('checkbox')
    // checkboxes[0] is the header "select all"; [1] and [2] are the two rows.
    await userEvent.click(checkboxes[1])

    // One selected → still no 对比 button (needs exactly 2).
    expect(screen.queryByRole('button', { name: /对\s?比/ })).not.toBeInTheDocument()

    await userEvent.click(checkboxes[2])

    const compareBtn = await screen.findByRole('button', { name: /对\s?比/ })
    await userEvent.click(compareBtn)

    expect(await screen.findByText('compare-page?a=b1&b=b2')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Batches/List.test.tsx -t "对比"`
Expected: FAIL — the `对比` button is never found (`Unable to find role="button" and name /对\s?比/`).

- [ ] **Step 3: Add the button to the selection toolbar**

In `web/src/pages/Batches/List.tsx`, the selection toolbar is the `<Space>` shown when `selectedIds.length > 0` (around lines 932-961). Add the 对比 button as the first action inside that `<Space>`, immediately after the `已选 {selectedIds.length} 项` span and before the first `<Popconfirm>`:

```tsx
              <span style={{ fontSize: 13 }}>已选 {selectedIds.length} 项</span>
              {selectedIds.length === 2 ? (
                <Button
                  size="small"
                  onClick={() => navigate(`/batches/compare?a=${selectedIds[0]}&b=${selectedIds[1]}`)}
                >
                  对比
                </Button>
              ) : null}
              <Popconfirm
```

`navigate` and `Button` are already imported and in scope in this file (used elsewhere on the page).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm test -- --run src/pages/Batches/List.test.tsx`
Expected: PASS (all existing List tests plus the new 对比 test).

- [ ] **Step 5: Typecheck + lint**

Run: `cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add web/src/pages/Batches/List.tsx web/src/pages/Batches/List.test.tsx
git commit -m "feat(web): add 对比 button to the Batches List selection toolbar"
```

---

## Task 5: Full verification + docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full frontend suite + build**

Run:
```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest/web && pnpm exec tsc --noEmit && pnpm lint && pnpm test -- --run && pnpm build
```
Expected: typecheck clean, lint clean, all tests pass, build succeeds.

- [ ] **Step 2: Add the CLAUDE.md changelog entry**

In `CLAUDE.md`, add a new bullet in the "Development status" changelog list (alongside the other dated entries, e.g. right after the "Failure reason clustering (2026-08-03)" entry). Use this text:

```markdown
- **Batch comparison (diff) view (2026-08-03):** Batches List's existing checkbox selection gained a 对比 action (shown only when exactly 2 batches are selected) opening `/batches/compare?a=<id1>&b=<id2>` — a new `web/src/pages/Batches/Compare.tsx` page that fetches both batches via the existing `useBatch` hook (no backend change), aligns their samples by `Sample.id` (stable across rerun/replay and across resubmitting the same JSON batch definition — the two natural "compare two runs" scenarios), and renders an AntD `Table` with a per-sample duration delta (Δ = B − A, danger-red when B is slower, success-green when faster — directional, distinct from Batches List's magnitude-only duration-anomaly highlight) plus, on expand, a word-level highlighted diff of each side's *effective* response. Alignment/effective-response logic is a pure function (`web/src/utils/batchComparison.ts::buildBatchComparison`) reusing `selectEffectiveResponseText` so this view can't drift from what every other "what response did this sample actually produce" surface shows (the exact drift class that's bitten this codebase before). Only the first prompt round is compared (multi-round comparison is a deferred non-goal); samples present in only one batch are called out with a 仅 A/仅 B tag and aren't expandable. Word-level diffing uses the new `diff` (jsdiff) dependency via a small theme-aware `web/src/components/DiffText.tsx` (added = success bg, removed = error bg + strikethrough, colors from AntD tokens so it reads correctly in dark mode), computed lazily only when a row is expanded. Design: `docs/superpowers/specs/2026-08-03-batch-comparison-design.md`; plan: `docs/superpowers/plans/2026-08-03-batch-comparison.md`.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/b1ankj/Code/2026/Q2/AutoAgentTest
git add CLAUDE.md
git commit -m "docs: log the batch comparison feature"
```

- [ ] **Step 4: Finish**

After all tasks are committed, use the finishing-a-development-branch skill. Note: this work is on `main` directly (no separate branch/worktree, matching this session's established pattern), so the skill's merge/PR/worktree options don't apply — instead verify the full suite is green (Step 1), then ask the user whether to push. On confirmation, push and verify CI green via `gh run list` → `gh run watch --exit-status` → `gh run view --json conclusion,status`.

---

## Self-Review

**1. Spec coverage:**
- Entry point (reuse checkboxes, `対比` at exactly 2, navigate to `/batches/compare?a=&b=`) → Task 4. ✓
- Align by `Sample.id` → Task 1. ✓
- Per-sample duration + colored delta → Task 3 (`DeltaCell`). ✓
- Word-level diff of effective response on expand → Task 2 (`DiffText`) + Task 3 (`expandedRowRender`). ✓
- Reuse `selectEffectiveResponseText` → Task 1 (`sideOf`). ✓
- Samples only in one batch called out, not diffed → Task 1 (`null` side) + Task 3 (tags + `rowExpandable`). ✓
- First round only → Task 1 (`[0]` indexing), covered by a test. ✓
- No backend change → confirmed; only `useBatch`. ✓
- `diff` (jsdiff) new dependency → Task 2. ✓
- Loading/error states reuse `PageSkeleton`/`ErrorState` → Task 3. ✓
- Header with links back to each batch → Task 3 (subtitle). ✓
- Summary line "N 个共同 · M 个仅 A · K 个仅 B" → Task 3. ✓
- Zero common samples → empty table with `locale.emptyText` + summary still shown → Task 3. ✓
- Testing: pure-function unit test (Task 1), component test (Task 3), Batches List button-gating test (Task 4). ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/vague steps — every code step has complete code. ✓

**3. Type consistency:** `SampleSide`/`SampleComparisonRow`/`BatchComparison` defined in Task 1 are the exact names imported/used in Task 3. `buildBatchComparison(samplesA, samplesB)` signature matches the Task 3 call `buildBatchComparison(aQ.data.samples, bQ.data.samples)`. `DiffText` props `{ before, after }` match both Task 2's definition and Task 3's usage. `formatDurationMs` matches the existing `web/src/utils/duration.ts` export. ✓
