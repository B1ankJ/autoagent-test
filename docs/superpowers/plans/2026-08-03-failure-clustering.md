# Failure Reason Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsible "错误分组" panel above Batches Detail's sample table that groups failed samples by normalized `error` text (count + example per group), with click-to-filter into the existing table.

**Architecture:** A pure function (`groupFailuresByError`) normalizes each failed sample's `error` text via a fixed set of regex substitutions (strip timeouts/coordinates/device serials/hex ids/timestamps) and groups by exact match of the result. A new `FailureClusterPanel` component renders the groups; Batches Detail gains one new piece of state (`activeClusterId`) that ANDs into its existing `filteredSamples` computation alongside the current status filter and free-text search.

**Tech Stack:** React, TypeScript, AntD 5 (`Collapse`, `Tag`, `Typography.Paragraph`), Vitest + Testing Library.

Design spec: `docs/superpowers/specs/2026-08-03-failure-clustering-design.md`

---

## Task 1: Clustering logic (`failureClustering.ts`)

**Files:**
- Create: `web/src/utils/failureClustering.ts`
- Test: `web/src/utils/failureClustering.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// web/src/utils/failureClustering.test.ts
import { describe, expect, it } from 'vitest'
import { groupFailuresByError, normalizeError } from './failureClustering'
import type { Sample } from '../types/api'

describe('normalizeError', () => {
  it('replaces a millisecond timeout', () => {
    expect(normalizeError('timeout 30000ms exceeded')).toBe('timeout <MS>ms exceeded')
  })

  it('replaces a decimal-second duration', () => {
    expect(normalizeError('waited 5.2s for selector')).toBe('waited <N>s for selector')
  })

  it('replaces a tap coordinate pair', () => {
    expect(normalizeError('tap at (495, 2059) failed')).toBe('tap at (<X>, <Y>) failed')
  })

  it('replaces an emulator device serial', () => {
    expect(normalizeError('device offline: emulator-5554')).toBe('device offline: <DEVICE>')
  })

  it('replaces a hex id that contains at least one digit', () => {
    expect(normalizeError('session abc123def456 not found')).toBe('session <ID> not found')
  })

  it('does not treat an all-letter word that happens to be hex-safe as an id', () => {
    // "facade" is 6 letters, all within a-f, but has no digit — a real word,
    // not an id, must not be replaced. This is exactly the false-positive
    // class the digit-lookahead in the id rule exists to avoid.
    expect(normalizeError('applied a facade wrapper')).toBe('applied a facade wrapper')
  })

  it('replaces an ISO-ish timestamp', () => {
    expect(normalizeError('failed at 2026-08-03T00:00:00Z')).toBe('failed at <TIMESTAMP>')
  })

  it('leaves quoted locator/selector content untouched', () => {
    expect(normalizeError("element not found: '#send-button'")).toBe(
      "element not found: '#send-button'",
    )
  })
})

function failedSample(id: string, error: string): Sample {
  return { id, prompts: ['x'], mode: 'api', target_profile: 'p', status: 'failed', error }
}

describe('groupFailuresByError', () => {
  it('returns nothing when there are no failed samples', () => {
    const samples: Sample[] = [
      { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', status: 'done' },
    ]
    expect(groupFailuresByError(samples)).toEqual([])
  })

  it('ignores a failed sample with no error text', () => {
    const samples: Sample[] = [
      { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', status: 'failed' },
    ]
    expect(groupFailuresByError(samples)).toEqual([])
  })

  it('groups errors that normalize to the same pattern', () => {
    const samples = [
      failedSample('s1', 'device offline: emulator-5554'),
      failedSample('s2', 'device offline: emulator-5556'),
    ]
    const groups = groupFailuresByError(samples)
    expect(groups).toEqual([
      {
        pattern: 'device offline: <DEVICE>',
        count: 2,
        sampleIds: ['s1', 's2'],
        example: 'device offline: emulator-5554',
      },
    ])
  })

  it('keeps genuinely different errors in separate groups', () => {
    const samples = [
      failedSample('s1', "element not found: '#send-button'"),
      failedSample('s2', "element not found: '#input'"),
    ]
    expect(groupFailuresByError(samples)).toHaveLength(2)
  })

  it('sorts groups by count descending', () => {
    const samples = [
      failedSample('s1', 'timeout 1000ms'),
      failedSample('s2', 'device offline: emulator-5554'),
      failedSample('s3', 'device offline: emulator-5556'),
      failedSample('s4', 'device offline: emulator-5558'),
    ]
    const groups = groupFailuresByError(samples)
    expect(groups.map((g) => g.count)).toEqual([3, 1])
    expect(groups[0].pattern).toBe('device offline: <DEVICE>')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && pnpm exec vitest run src/utils/failureClustering.test.ts`
Expected: FAIL — `Cannot find module './failureClustering'`

- [ ] **Step 3: Write the implementation**

```ts
// web/src/utils/failureClustering.ts
import type { Sample } from '../types/api'

export interface FailureCluster {
  pattern: string
  count: number
  sampleIds: string[]
  example: string
}

// Order matters: the ms rule must run before the "s" duration rule so
// "30000ms" becomes "<MS>ms" first — by the time the "s" rule runs, there
// are no digits left directly before that "ms" for it to also match.
const NORMALIZATION_RULES: Array<[RegExp, string]> = [
  [/\d+(\.\d+)?ms\b/g, '<MS>ms'],
  [/\b\d+(\.\d+)?s\b/g, '<N>s'],
  [/\(\s*-?\d+\s*,\s*-?\d+\s*\)/g, '(<X>, <Y>)'],
  [/\bemulator-\d+\b/g, '<DEVICE>'],
  // Requires at least one digit in the run (via the lookahead) so a plain
  // English word that happens to use only a-f letters (e.g. "facade",
  // "deface") isn't mistaken for a hex id — real ids/hashes/serials always
  // have at least one digit in practice.
  [/\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{6,}\b/g, '<ID>'],
  [/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*/g, '<TIMESTAMP>'],
]

/** Replaces run-specific variable substrings (timeouts, coordinates, device
 * serials, hex ids, timestamps) in an error string with placeholder tokens,
 * so two errors with the same root cause but different embedded details
 * normalize to the same string. Deliberately does not touch quoted content
 * (locator/selector strings) — two "element not found" errors for two
 * different selectors are a real distinction worth keeping separate. */
export function normalizeError(error: string): string {
  return NORMALIZATION_RULES.reduce(
    (text, [pattern, replacement]) => text.replace(pattern, replacement),
    error,
  )
}

/** Groups a batch's failed samples by normalized error text, sorted by
 * count descending (ties keep first-appearance order — Array.sort is
 * stable, and Map preserves insertion order). */
export function groupFailuresByError(samples: Sample[]): FailureCluster[] {
  const groups = new Map<string, { sampleIds: string[]; example: string }>()
  for (const sample of samples) {
    if (sample.status !== 'failed' || !sample.error) continue
    const pattern = normalizeError(sample.error)
    const existing = groups.get(pattern)
    if (existing) {
      existing.sampleIds.push(sample.id)
    } else {
      groups.set(pattern, { sampleIds: [sample.id], example: sample.error })
    }
  }
  return [...groups.entries()]
    .map(([pattern, { sampleIds, example }]) => ({
      pattern,
      count: sampleIds.length,
      sampleIds,
      example,
    }))
    .sort((a, b) => b.count - a.count)
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && pnpm exec vitest run src/utils/failureClustering.test.ts`
Expected: PASS (14 tests)

- [ ] **Step 5: Lint and typecheck**

Run: `cd web && pnpm lint && pnpm exec tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add web/src/utils/failureClustering.ts web/src/utils/failureClustering.test.ts
git commit -m "feat(web): add the failure-reason normalize/group logic"
```

---

## Task 2: `FailureClusterPanel` component

**Files:**
- Create: `web/src/components/FailureClusterPanel.tsx`
- Test: `web/src/components/FailureClusterPanel.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// web/src/components/FailureClusterPanel.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { FailureClusterPanel } from './FailureClusterPanel'
import type { Sample } from '../types/api'

function failedSample(id: string, error: string): Sample {
  return { id, prompts: ['x'], mode: 'api', target_profile: 'p', status: 'failed', error }
}

it('renders nothing with fewer than 2 failed samples', () => {
  const samples = [failedSample('s1', 'device offline: emulator-5554')]
  const { container } = render(
    <FailureClusterPanel samples={samples} activeClusterId={null} onSelectCluster={vi.fn()} />,
  )
  expect(container).toBeEmptyDOMElement()
})

it('renders one row per cluster with its count, sorted by count descending', async () => {
  const samples = [
    failedSample('s1', 'timeout 1000ms'),
    failedSample('s2', 'device offline: emulator-5554'),
    failedSample('s3', 'device offline: emulator-5556'),
  ]
  render(<FailureClusterPanel samples={samples} activeClusterId={null} onSelectCluster={vi.fn()} />)

  // Collapsed by default — open it to see the group rows.
  await userEvent.click(screen.getByText(/错误分组/))
  expect(screen.getByText('device offline: <DEVICE>')).toBeInTheDocument()
  expect(screen.getByText('2')).toBeInTheDocument()
  expect(screen.getByText('device offline: emulator-5554')).toBeInTheDocument()
})

it('calls onSelectCluster with the pattern id when 筛选 is clicked, and null when clicked again', async () => {
  const samples = [
    failedSample('s1', 'device offline: emulator-5554'),
    failedSample('s2', 'device offline: emulator-5556'),
  ]
  const onSelectCluster = vi.fn()
  const { rerender } = render(
    <FailureClusterPanel samples={samples} activeClusterId={null} onSelectCluster={onSelectCluster} />,
  )
  await userEvent.click(screen.getByText(/错误分组/))
  await userEvent.click(screen.getByRole('button', { name: /筛\s?选/ }))
  expect(onSelectCluster).toHaveBeenCalledWith('device offline: <DEVICE>')

  rerender(
    <FailureClusterPanel
      samples={samples}
      activeClusterId="device offline: <DEVICE>"
      onSelectCluster={onSelectCluster}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /取消筛选/ }))
  expect(onSelectCluster).toHaveBeenCalledWith(null)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && pnpm exec vitest run src/components/FailureClusterPanel.test.tsx`
Expected: FAIL — `Cannot find module './FailureClusterPanel'`

- [ ] **Step 3: Write the implementation**

```tsx
// web/src/components/FailureClusterPanel.tsx
import { Button, Collapse, Space, Tag, Typography } from 'antd'
import { groupFailuresByError } from '../utils/failureClustering'
import type { Sample } from '../types/api'

interface Props {
  samples: Sample[]
  activeClusterId: string | null
  onSelectCluster: (id: string | null) => void
}

const MIN_FAILURES_TO_SHOW = 2

export function FailureClusterPanel({ samples, activeClusterId, onSelectCluster }: Props) {
  const clusters = groupFailuresByError(samples)
  const failedCount = clusters.reduce((sum, c) => sum + c.count, 0)

  if (failedCount < MIN_FAILURES_TO_SHOW) return null

  return (
    <Collapse
      style={{ marginBottom: 12 }}
      items={[
        {
          key: 'clusters',
          label: `错误分组 (${clusters.length})`,
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              {clusters.map((cluster) => {
                const isActive = activeClusterId === cluster.pattern
                return (
                  <div
                    key={cluster.pattern}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: 8,
                      border: '1px solid var(--aa-border, #e5e5e5)',
                      borderRadius: 6,
                      background: isActive ? 'var(--aa-surface-alt)' : undefined,
                    }}
                  >
                    <Tag color="blue">{cluster.count}</Tag>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Typography.Text className="aa-mono" strong>
                        {cluster.pattern}
                      </Typography.Text>
                      <Typography.Paragraph
                        type="secondary"
                        style={{ marginBottom: 0, fontSize: 12 }}
                        ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                      >
                        {cluster.example}
                      </Typography.Paragraph>
                    </div>
                    <Button
                      size="small"
                      type={isActive ? 'primary' : 'default'}
                      onClick={() => onSelectCluster(isActive ? null : cluster.pattern)}
                    >
                      {isActive ? '取消筛选' : '筛选'}
                    </Button>
                  </div>
                )
              })}
            </Space>
          ),
        },
      ]}
    />
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && pnpm exec vitest run src/components/FailureClusterPanel.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Lint and typecheck**

Run: `cd web && pnpm lint && pnpm exec tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add web/src/components/FailureClusterPanel.tsx web/src/components/FailureClusterPanel.test.tsx
git commit -m "feat(web): add the FailureClusterPanel component"
```

---

## Task 3: Wire into Batches Detail

**Files:**
- Modify: `web/src/pages/Batches/Detail.tsx`
- Modify: `web/src/pages/Batches/Detail.test.tsx`

- [ ] **Step 1: Add the import and `activeClusterId` state**

Find:
```tsx
import { RunningThumbGrid } from '../../components/RunningThumbGrid'
```

Add right after it:
```tsx
import { FailureClusterPanel } from '../../components/FailureClusterPanel'
```

Find:
```tsx
  const [filter, setFilter] = useState<SampleFilter>('all')
  const [search, setSearch] = useState('')
```

Replace with:
```tsx
  const [filter, setFilter] = useState<SampleFilter>('all')
  const [search, setSearch] = useState('')
  const [activeClusterId, setActiveClusterId] = useState<string | null>(null)
```

- [ ] **Step 2: Fold `activeClusterId` into `filteredSamples`**

Find:
```tsx
  const filteredSamples = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allSamples.filter((s) => {
      if (filter !== 'all' && s.status !== filter) return false
      if (!q) return true
      if (s.id.toLowerCase().includes(q)) return true
      if (s.error && s.error.toLowerCase().includes(q)) return true
      if ((s.prompts_sent ?? s.prompts)?.some((p) => p.toLowerCase().includes(q))) return true
      if (s.responses?.some((r) => r.toLowerCase().includes(q))) return true
      if (s.llm_responses?.some((r) => r?.toLowerCase().includes(q))) return true
      return false
    })
  }, [allSamples, filter, search])
```

Replace with:
```tsx
  const failureClusters = useMemo(() => groupFailuresByError(allSamples), [allSamples])
  const activeClusterSampleIds = useMemo(() => {
    if (!activeClusterId) return null
    const cluster = failureClusters.find((c) => c.pattern === activeClusterId)
    return cluster ? new Set(cluster.sampleIds) : new Set<string>()
  }, [failureClusters, activeClusterId])

  const filteredSamples = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allSamples.filter((s) => {
      if (filter !== 'all' && s.status !== filter) return false
      if (activeClusterSampleIds && !activeClusterSampleIds.has(s.id)) return false
      if (!q) return true
      if (s.id.toLowerCase().includes(q)) return true
      if (s.error && s.error.toLowerCase().includes(q)) return true
      if ((s.prompts_sent ?? s.prompts)?.some((p) => p.toLowerCase().includes(q))) return true
      if (s.responses?.some((r) => r.toLowerCase().includes(q))) return true
      if (s.llm_responses?.some((r) => r?.toLowerCase().includes(q))) return true
      return false
    })
  }, [allSamples, filter, search, activeClusterSampleIds])
```

Add the import this needs — find:
```tsx
import { Sample } from '../../types/api'
```

Replace with:
```tsx
import { Sample } from '../../types/api'
import { groupFailuresByError } from '../../utils/failureClustering'
```

- [ ] **Step 3: Render the panel above the sample table**

Find:
```tsx
          <Space wrap style={{ marginBottom: 12 }}>
            <Segmented<SampleFilter>
```

Replace with:
```tsx
          <FailureClusterPanel
            samples={allSamples}
            activeClusterId={activeClusterId}
            onSelectCluster={setActiveClusterId}
          />
          <Space wrap style={{ marginBottom: 12 }}>
            <Segmented<SampleFilter>
```

- [ ] **Step 4: Run typecheck to catch anything missed**

Run: `cd web && pnpm exec tsc --noEmit`
Expected: no errors (if `failureClusters` ends up unused by TS's reckoning anywhere, that's fine — it's used by both `activeClusterSampleIds` and implicitly available for future use, but double check no `noUnusedLocals` complaint; it IS used, so this should be clean)

- [ ] **Step 5: Add an integration test for the new filter-composition behavior**

Read the existing mocking setup at the top of `web/src/pages/Batches/Detail.test.tsx` first (`useBatchStream` mock, `renderWithProviders` pattern used by the other tests in that file) and follow it exactly. Add this test:

```tsx
it('composes the failure-cluster filter with the existing status filter (AND, not OR)', async () => {
  useBatchStream.mockReturnValue({
    data: {
      batch_id: 'b1',
      name: 'Test',
      mode: 'api',
      status: 'done',
      total: 3,
      done: 1,
      failed: 2,
      concurrency: 1,
      seq: 4,
      samples: [
        { id: 's1', prompts: ['x'], mode: 'api', target_profile: 'p', status: 'done' },
        {
          id: 's2',
          prompts: ['x'],
          mode: 'api',
          target_profile: 'p',
          status: 'failed',
          error: 'device offline: emulator-5554',
        },
        {
          id: 's3',
          prompts: ['x'],
          mode: 'api',
          target_profile: 'p',
          status: 'failed',
          error: 'device offline: emulator-5556',
        },
      ],
    },
    isLoading: false,
  })
  useCancelBatch.mockReturnValue({ mutateAsync: vi.fn() })
  useReplayBatch.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })

  renderWithProviders(
    <Routes>
      <Route path="/batches/:id" element={<BatchDetail />} />
    </Routes>,
    { initialPath: '/batches/b1' },
  )

  await waitFor(() => expect(screen.getByText('Test')).toBeInTheDocument())
  await userEvent.click(screen.getByText(/错误分组/))
  await userEvent.click(screen.getByRole('button', { name: /筛\s?选/ }))

  // Both s2 and s3 are in the one cluster — both should now be the only
  // rows shown (the table itself, not just the panel's own count).
  const table = screen.getByRole('table')
  expect(within(table).getByText('s2')).toBeInTheDocument()
  expect(within(table).getByText('s3')).toBeInTheDocument()
  expect(within(table).queryByText('s1')).not.toBeInTheDocument()
})
```

Check the top of the test file for whether `userEvent` and `within` are already imported (other tests in this file already use `within` per `web/src/pages/Batches/Detail.test.tsx`'s existing `返回 link` tests) — add whichever import is missing from `@testing-library/react` / `@testing-library/user-event`.

- [ ] **Step 6: Run the full Detail test file**

Run: `cd web && pnpm exec vitest run src/pages/Batches/Detail.test.tsx`
Expected: PASS (all tests, including the 6 pre-existing ones — none of their fixtures have 2+ failed samples, so `FailureClusterPanel` renders `null` for them and shouldn't affect anything they already assert)

- [ ] **Step 7: Lint and typecheck**

Run: `cd web && pnpm lint && pnpm exec tsc --noEmit`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/Batches/Detail.tsx web/src/pages/Batches/Detail.test.tsx
git commit -m "feat(web): show a failure-cluster panel on Batches Detail, filterable into the sample table"
```

---

## Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd web && pnpm test`
Expected: all test files pass, no regressions in unrelated files

- [ ] **Step 2: Build**

Run: `cd web && pnpm build`
Expected: builds successfully (pre-existing "chunk larger than 1500 kB" warning is expected and unrelated)

- [ ] **Step 3: Manual smoke check (if a browser session is available)**

Open a batch with several failed samples sharing a root cause (or fake it by editing sample data). Confirm: 错误分组 panel appears collapsed by default when there are 2+ failures, expands to show grouped counts, 筛选 narrows the table below and the button flips to 取消筛选, clicking it again clears the filter.

- [ ] **Step 4: Update CLAUDE.md**

Add a dated bullet to the "Development status" section (match the style of adjacent entries) describing: Batches Detail gained a 错误分组 panel (`web/src/components/FailureClusterPanel.tsx`, grouping logic in `web/src/utils/failureClustering.ts`) that groups failed samples by regex-normalized `error` text and lets clicking a group filter the sample table (composes with the existing status/search filters). Scoped to one batch at a time; cross-batch clustering is a follow-up.

- [ ] **Step 5: Commit the CLAUDE.md update**

```bash
git add CLAUDE.md
git commit -m "docs: log the failure reason clustering feature"
```
