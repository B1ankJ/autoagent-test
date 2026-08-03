# Sample Replay Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SampleDetail's separate screenshot strip + action-log table with one scrubbable timeline (big image + bottom slider) for `gui_pc_web`/`gui_android` samples, built entirely client-side from data already fetched today.

**Architecture:** A pure function (`buildTimelineEvents`) merges `sample.metadata.action_log` (has `t_ms`, relative) and the existing screenshot list (has `taken_at`, absolute) into one sorted array, anchored on the first screenshot's timestamp as t=0. A new component (`SampleReplayTimeline`) renders that array as a big image (nearest screenshot at-or-before the selected index) + an AntD `Slider` with per-event marks; selecting an action-kind event also shows its target/success detail below the image, reusing the existing `formatActionTarget` logic (moved out of `SampleDetail.tsx`, its only caller).

**Tech Stack:** React, TypeScript, AntD 5 (`Slider`), TanStack Query (existing `listScreenshots`), Vitest + Testing Library.

Design spec: `docs/superpowers/specs/2026-07-31-sample-replay-timeline-design.md`

---

## Task 1: Timeline merge logic (`replayTimeline.ts`)

**Files:**
- Create: `web/src/utils/replayTimeline.ts`
- Test: `web/src/utils/replayTimeline.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// web/src/utils/replayTimeline.test.ts
import { describe, expect, it } from 'vitest'
import { buildTimelineEvents, formatActionTarget, type ActionLogEntry } from './replayTimeline'
import type { ScreenshotInfo } from '../types/api'

describe('buildTimelineEvents', () => {
  it('returns an empty array when there is nothing at all', () => {
    expect(buildTimelineEvents([], [])).toEqual([])
  })

  it('sorts screenshot-only input by taken_at, anchored so the first is elapsedMs=0', () => {
    const shots: ScreenshotInfo[] = [
      { name: 'a.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
      { name: 'b.jpg', label: 'done', taken_at: '2026-01-01T00:00:02.500Z' },
    ]
    const events = buildTimelineEvents([], shots)
    expect(events).toEqual([
      { kind: 'screenshot', elapsedMs: 0, screenshot: shots[0] },
      { kind: 'screenshot', elapsedMs: 2500, screenshot: shots[1] },
    ])
  })

  it('sorts action-only input by t_ms directly', () => {
    const actions: ActionLogEntry[] = [
      { t_ms: 500, action: 'send' },
      { t_ms: 100, action: 'tap_xy', x: 1, y: 2 },
    ]
    const events = buildTimelineEvents(actions, [])
    expect(events.map((e) => e.elapsedMs)).toEqual([100, 500])
    expect(events[0]).toEqual({ kind: 'action', elapsedMs: 100, entry: actions[1] })
  })

  it('interleaves screenshots and actions on one sorted axis', () => {
    const shots: ScreenshotInfo[] = [
      { name: 'a.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
      { name: 'b.jpg', label: 'after_send', taken_at: '2026-01-01T00:00:01.000Z' },
    ]
    const actions: ActionLogEntry[] = [{ t_ms: 500, action: 'tap_xy', x: 1, y: 2 }]
    const events = buildTimelineEvents(actions, shots)
    expect(events.map((e) => e.kind)).toEqual(['screenshot', 'action', 'screenshot'])
    expect(events.map((e) => e.elapsedMs)).toEqual([0, 500, 1000])
  })

  it('breaks a tie (identical elapsedMs) by putting the screenshot first', () => {
    const shots: ScreenshotInfo[] = [
      { name: 'a.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
    ]
    const actions: ActionLogEntry[] = [{ t_ms: 0, action: 'tap_xy', x: 1, y: 2 }]
    const events = buildTimelineEvents(actions, shots)
    expect(events.map((e) => e.kind)).toEqual(['screenshot', 'action'])
  })
})

describe('formatActionTarget', () => {
  it('formats a tap coordinate', () => {
    expect(formatActionTarget({ x: 495, y: 2059 })).toBe('(495, 2059)')
  })

  it('formats a locator', () => {
    expect(formatActionTarget({ locator: { type: 'xpath', value: '//*[@text="发送"]' } })).toBe(
      'xpath://*[@text="发送"]',
    )
  })

  it('formats a swipe path', () => {
    expect(formatActionTarget({ x1: 1, y1: 2, x2: 3, y2: 4 })).toBe('(1, 2) -> (3, 4)')
  })

  it('falls back to "-" for an unrecognized shape', () => {
    expect(formatActionTarget({})).toBe('-')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && pnpm exec vitest run src/utils/replayTimeline.test.ts`
Expected: FAIL — `Cannot find module './replayTimeline'` (file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```ts
// web/src/utils/replayTimeline.ts
import type { ScreenshotInfo } from '../types/api'

export interface ActionLogEntry {
  t_ms: number
  action?: string
  ok?: boolean
  error?: string
  x?: number
  y?: number
  x1?: number
  y1?: number
  x2?: number
  y2?: number
  locator?: { type?: string; value?: string }
  key?: string
  package?: string
  activity?: string
  url?: string
  text_length?: number
}

export type TimelineEvent =
  | { kind: 'screenshot'; elapsedMs: number; screenshot: ScreenshotInfo }
  | { kind: 'action'; elapsedMs: number; entry: ActionLogEntry }

/**
 * Merges action_log (t_ms, relative to when the action loop started) and
 * screenshots (taken_at, absolute) onto one sorted time axis. Anchored on
 * the first screenshot's taken_at as elapsedMs=0 — that's always the
 * "ready" milestone, captured right when the action loop (and its t_ms
 * clock) starts, so the two series line up closely enough for a debugging
 * timeline without needing any backend change to record a shared clock.
 */
export function buildTimelineEvents(
  actionLog: ActionLogEntry[],
  screenshots: ScreenshotInfo[],
): TimelineEvent[] {
  const firstShotMs =
    screenshots.length > 0 ? new Date(screenshots[0].taken_at).getTime() : 0

  const screenshotEvents: TimelineEvent[] = screenshots.map((screenshot) => ({
    kind: 'screenshot',
    elapsedMs: new Date(screenshot.taken_at).getTime() - firstShotMs,
    screenshot,
  }))
  const actionEvents: TimelineEvent[] = actionLog.map((entry) => ({
    kind: 'action',
    elapsedMs: entry.t_ms,
    entry,
  }))

  // Array.prototype.sort is stable (guaranteed since ES2019) — screenshots
  // are concatenated first, so a tie keeps the screenshot ahead of the
  // action, a reasonable default ("here's the frame, then what happened").
  return [...screenshotEvents, ...actionEvents].sort((a, b) => a.elapsedMs - b.elapsedMs)
}

function formatLocator(locator: unknown): string {
  if (!locator || typeof locator !== 'object') return '-'
  const maybeLocator = locator as { type?: unknown; value?: unknown }
  if (typeof maybeLocator.type === 'string' && typeof maybeLocator.value === 'string') {
    return `${maybeLocator.type}:${maybeLocator.value}`
  }
  return '-'
}

/** Moved here from SampleDetail.tsx (its only caller) — describes an
 * action_log entry's target in one short string for display. */
export function formatActionTarget(record: Record<string, unknown>): string {
  if (typeof record.x === 'number' && typeof record.y === 'number') {
    return `(${record.x}, ${record.y})`
  }
  if (record.locator) {
    return formatLocator(record.locator)
  }
  if (typeof record.url === 'string') {
    return record.url
  }
  if (
    typeof record.x1 === 'number' &&
    typeof record.y1 === 'number' &&
    typeof record.x2 === 'number' &&
    typeof record.y2 === 'number'
  ) {
    return `(${record.x1}, ${record.y1}) -> (${record.x2}, ${record.y2})`
  }
  if (typeof record.key === 'string') {
    return record.key
  }
  if (typeof record.package === 'string' && typeof record.activity === 'string') {
    return `${record.package}/${record.activity}`
  }
  if (typeof record.package === 'string') {
    return record.package
  }
  return '-'
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && pnpm exec vitest run src/utils/replayTimeline.test.ts`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint and typecheck**

Run: `cd web && pnpm lint && pnpm exec tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add web/src/utils/replayTimeline.ts web/src/utils/replayTimeline.test.ts
git commit -m "feat(web): add the screenshot/action-log timeline merge logic"
```

---

## Task 2: `SampleReplayTimeline` component

**Files:**
- Create: `web/src/components/SampleReplayTimeline.tsx`
- Test: `web/src/components/SampleReplayTimeline.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// web/src/components/SampleReplayTimeline.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import { SampleReplayTimeline } from './SampleReplayTimeline'

const { listScreenshots } = vi.hoisted(() => ({ listScreenshots: vi.fn() }))

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotUrl: (batchId: string, sampleId: string, name: string) =>
    `/api/v1/media/batches/${batchId}/samples/${sampleId}/screenshot/${name}`,
}))

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const SCREENSHOTS = [
  { name: 'ready.jpg', label: 'ready', taken_at: '2026-01-01T00:00:00.000Z' },
  { name: 'done.jpg', label: 'done', taken_at: '2026-01-01T00:00:01.000Z' },
]

const ACTION_LOG = [
  { t_ms: 300, action: 'tap_xy', x: 495, y: 2059, ok: true },
  {
    t_ms: 600,
    action: 'click_locator',
    locator: { type: 'xpath', value: '//*[@text="发送"]' },
    ok: false,
    error: 'element not found',
  },
]

it('shows an empty state with no screenshots and no action log', async () => {
  listScreenshots.mockResolvedValue([])
  renderWithClient(
    <SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={undefined} />,
  )
  expect(await screen.findByText('暂无截图')).toBeInTheDocument()
})

it('renders screenshot-only marks when there is no action_log (fallback mode)', async () => {
  listScreenshots.mockResolvedValue(SCREENSHOTS)
  renderWithClient(
    <SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={undefined} />,
  )
  await waitFor(() => expect(screen.getAllByRole('slider')).toHaveLength(1))
  expect(screen.getByRole('img')).toHaveAttribute(
    'src',
    '/api/v1/media/batches/b1/samples/s1/screenshot/done.jpg',
  )
})

it('defaults to the last event and lets keyboard arrows scrub backward through actions', async () => {
  listScreenshots.mockResolvedValue(SCREENSHOTS)
  renderWithClient(
    <SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={ACTION_LOG} />,
  )

  // Merged order: ready(0ms), tap_xy(300ms), click_locator(600ms), done(1000ms)
  // — default selection is the last event (the "done" screenshot).
  await waitFor(() =>
    expect(screen.getByRole('img')).toHaveAttribute(
      'src',
      '/api/v1/media/batches/b1/samples/s1/screenshot/done.jpg',
    ),
  )

  const handle = screen.getAllByRole('slider')[0]
  handle.focus()
  fireEvent.keyDown(handle, { key: 'ArrowLeft' })
  expect(await screen.findByText('xpath://*[@text="发送"]')).toBeInTheDocument()
  expect(screen.getByText('element not found')).toBeInTheDocument()

  fireEvent.keyDown(handle, { key: 'ArrowLeft' })
  expect(await screen.findByText('(495, 2059)')).toBeInTheDocument()
})

it('shows a retry button when the screenshot list fails to load', async () => {
  listScreenshots.mockRejectedValue(new Error('boom'))
  renderWithClient(
    <SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={undefined} />,
  )
  expect(await screen.findByText('截图加载失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && pnpm exec vitest run src/components/SampleReplayTimeline.test.tsx`
Expected: FAIL — `Cannot find module './SampleReplayTimeline'`

- [ ] **Step 3: Write the implementation**

```tsx
// web/src/components/SampleReplayTimeline.tsx
import { PictureOutlined, WarningOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Skeleton, Slider, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { listScreenshots, screenshotUrl } from '../api/screenshots'
import {
  ActionLogEntry,
  TimelineEvent,
  buildTimelineEvents,
  formatActionTarget,
} from '../utils/replayTimeline'

interface Props {
  batchId: string
  sampleId: string
  // Raw sample.metadata.action_log — validated here so the caller doesn't
  // need to know this component's expected shape.
  actionLog: unknown
}

function isActionLogEntry(value: unknown): value is ActionLogEntry {
  return (
    !!value && typeof value === 'object' && typeof (value as ActionLogEntry).t_ms === 'number'
  )
}

function findNearestScreenshot(events: TimelineEvent[], index: number) {
  for (let i = index; i >= 0; i--) {
    const event = events[i]
    if (event.kind === 'screenshot') return event.screenshot
  }
  return null
}

function markColor(event: TimelineEvent): string {
  if (event.kind === 'screenshot') return '#1677ff'
  return event.entry.ok === false ? '#ff4d4f' : '#52c41a'
}

function markTooltip(event: TimelineEvent): string {
  const seconds = (event.elapsedMs / 1000).toFixed(1)
  const what = event.kind === 'screenshot' ? event.screenshot.label : (event.entry.action ?? 'action')
  return `${what} · ${seconds}s`
}

export function SampleReplayTimeline({ batchId, sampleId, actionLog }: Props) {
  const screenshotsQ = useQuery({
    queryKey: ['screenshots', batchId, sampleId],
    queryFn: async () => listScreenshots(batchId, sampleId),
  })
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  const validActionLog = Array.isArray(actionLog) ? actionLog.filter(isActionLogEntry) : []
  const events = useMemo(
    () => buildTimelineEvents(validActionLog, screenshotsQ.data ?? []),
    // validActionLog is a fresh array each render but only its *contents*
    // matter here — re-deriving it every render is cheap (a handful of
    // entries), so this intentionally skips a deep-equality dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [actionLog, screenshotsQ.data],
  )

  if (screenshotsQ.isLoading) {
    return <Skeleton.Image active style={{ width: '100%', height: 320 }} />
  }

  if (screenshotsQ.isError) {
    return (
      <div
        style={{
          padding: '20px 0',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          color: 'var(--aa-amber)',
          fontSize: 13,
        }}
      >
        <WarningOutlined />
        截图加载失败
        <Button size="small" onClick={() => screenshotsQ.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (events.length === 0) {
    return (
      <div
        style={{
          padding: '20px 0',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          color: 'var(--aa-text-muted)',
          fontSize: 13,
        }}
      >
        <PictureOutlined />
        暂无截图
      </div>
    )
  }

  const index = Math.min(selectedIndex ?? events.length - 1, events.length - 1)
  const currentEvent = events[index]
  const currentImage = findNearestScreenshot(events, index)

  const marks: Record<number, { label: React.ReactNode; style: React.CSSProperties }> = {}
  events.forEach((event, i) => {
    marks[i] = {
      style: { fontSize: 0 },
      label: (
        <span
          style={{
            display: 'inline-block',
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: markColor(event),
          }}
        />
      ),
    }
  })

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          background: 'var(--aa-surface-alt)',
          borderRadius: 8,
          minHeight: 320,
        }}
      >
        {currentImage ? (
          <img
            src={screenshotUrl(batchId, sampleId, currentImage.name)}
            alt={currentImage.label}
            style={{ maxWidth: '100%', maxHeight: 480, objectFit: 'contain' }}
          />
        ) : (
          <Typography.Text type="secondary">这一步没有对应截图</Typography.Text>
        )}
      </div>
      {currentEvent.kind === 'action' ? (
        <Space size={8} wrap>
          <Tag color={currentEvent.entry.ok === false ? 'error' : 'success'}>
            {currentEvent.entry.ok === false ? '失败' : '成功'}
          </Tag>
          <Typography.Text className="aa-mono">{currentEvent.entry.action ?? '-'}</Typography.Text>
          <Typography.Text type="secondary" className="aa-mono">
            {formatActionTarget(currentEvent.entry as unknown as Record<string, unknown>)}
          </Typography.Text>
          {currentEvent.entry.error ? (
            <Typography.Text type="danger">{currentEvent.entry.error}</Typography.Text>
          ) : null}
        </Space>
      ) : (
        <Typography.Text type="secondary" className="aa-mono">
          {currentEvent.screenshot.label}
        </Typography.Text>
      )}
      <Slider
        min={0}
        max={events.length - 1}
        value={index}
        onChange={(value) => setSelectedIndex(value)}
        marks={marks}
        step={1}
        tooltip={{ formatter: (value) => (value !== undefined ? markTooltip(events[value]) : '') }}
      />
    </Space>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && pnpm exec vitest run src/components/SampleReplayTimeline.test.tsx`
Expected: PASS (4 tests)

If the `ArrowLeft` keyboard-scrub assertions don't move the slider by exactly one step, check AntD's `Slider` keyboard step handling — it defaults to moving by `step` (set to `1` above) per arrow press, which should exactly match one index. If it doesn't fire the way `onChange` expects in jsdom, try `fireEvent.keyDown(handle, { key: 'ArrowLeft', keyCode: 37 })` (some AntD versions check `keyCode` too).

- [ ] **Step 5: Lint and typecheck**

Run: `cd web && pnpm lint && pnpm exec tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add web/src/components/SampleReplayTimeline.tsx web/src/components/SampleReplayTimeline.test.tsx
git commit -m "feat(web): add the SampleReplayTimeline component"
```

---

## Task 3: Wire into SampleDetail, remove the old screenshot strip + action log table

**Files:**
- Modify: `web/src/pages/Batches/SampleDetail.tsx`
- Modify: `web/src/pages/Batches/SampleDetail.test.tsx`

- [ ] **Step 1: Remove the now-superseded code from `SampleDetail.tsx`**

Delete these (all now live in `replayTimeline.ts` / are no longer needed):
- The `formatLocator` function (lines ~18-25)
- The `formatActionTarget` function (lines ~27-55)
- The `useResizableColumns(...)` call building `actionLogColumns`/`actionLogComponents`/`actionLogScroll` (the block starting `const { columns: actionLogColumns, ... } = useResizableColumns([...` — search for `'autoagent_sample_action_log_col_widths'`)
- The `import { useResizableColumns } from '../../hooks/useResizableColumns'` line
- The `import { ScreenshotStrip } from '../../components/ScreenshotStrip'` line
- `Table` from the antd import list (`import { App, Button, Card, Collapse, Descriptions, Skeleton, Space, Table, Typography } from 'antd'` → remove `Table,`) — confirm nothing else in the file uses `<Table` first with `grep -n '<Table' web/src/pages/Batches/SampleDetail.tsx`.

Add:
```ts
import { SampleReplayTimeline } from '../../components/SampleReplayTimeline'
```

- [ ] **Step 2: Replace the 截图 Card and the 动作日志 Card with one `SampleReplayTimeline`**

Find:
```tsx
      <Card size="small" title="截图" style={{ marginBottom: 16 }}>
        <ScreenshotStrip batchId={data.batch_id} sampleId={sample.id} />
      </Card>
```

Replace with:
```tsx
      <Card size="small" title="截图" style={{ marginBottom: 16 }}>
        <SampleReplayTimeline
          batchId={data.batch_id}
          sampleId={sample.id}
          actionLog={sample.metadata?.action_log}
        />
      </Card>
```

Find and delete entirely (the whole conditional block, now folded into the component above):
```tsx
      {Array.isArray(sample.metadata?.action_log) && sample.metadata.action_log.length ? (
        <Card size="small" title="动作日志" style={{ marginBottom: 16 }}>
          <Table
            size="small"
            rowKey={(record) =>
              `${String(record.action ?? 'action')}-${String(record.t_ms ?? '-')}-${formatActionTarget(record)}`
            }
            pagination={false}
            dataSource={sample.metadata.action_log as Array<Record<string, unknown>>}
            columns={actionLogColumns}
            components={actionLogComponents}
            scroll={actionLogScroll}
            tableLayout="fixed"
          />
        </Card>
      ) : null}
```

- [ ] **Step 3: Update the two affected existing tests in `SampleDetail.test.tsx`**

The first test (`'shows screenshot links for the selected sample'`) currently asserts on `getByRole('img', { name: 'ready' })` with a thumbnail URL (`?w=336`) — `SampleReplayTimeline` shows one full-size image, no `w=` param. Update the relevant assertion block:

Find:
```tsx
    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(screen.getByRole('img', { name: 'ready' })).toHaveAttribute(
        'src',
        '/api/v1/media/batches/b1/samples/s1/screenshot/001_ready.png?w=336',
      )
    })
```

Replace with:
```tsx
    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(screen.getByRole('img', { name: 'ready' })).toHaveAttribute(
        'src',
        '/api/v1/media/batches/b1/samples/s1/screenshot/001_ready.png',
      )
    })
```

The second test (`'renders tap targets and metadata summaries for android samples'`) currently expects both action entries' formatted targets visible at once (the old table showed every row). With the timeline, only the selected event's detail shows — default selection is the last merged event. Given that test's fixture (one screenshot `after_send_1` + actions at `t_ms: 123` and `t_ms: 456`), the last event is the `t_ms: 456` action (`click_locator`). Update:

Find:
```tsx
    await waitFor(() => {
      expect(screen.getByText('动作日志')).toBeInTheDocument()
    })
    expect(screen.getByText('(495, 2059)')).toBeInTheDocument()
    expect(screen.getByText('xpath://*[@text="发送"]')).toBeInTheDocument()
    expect(screen.getByText('截图数量')).toBeInTheDocument()
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
```

Replace with:
```tsx
    await waitFor(() => {
      // Default selection is the last merged event — the second action
      // (t_ms: 456, click_locator) — so its target shows immediately.
      expect(screen.getByText('xpath://*[@text="发送"]')).toBeInTheDocument()
    })
    const handle = screen.getAllByRole('slider')[0]
    handle.focus()
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(await screen.findByText('(495, 2059)')).toBeInTheDocument()
    expect(screen.getByText('截图数量')).toBeInTheDocument()
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
```

This test file already imports `fireEvent`? Check: `grep -n "^import.*testing-library" web/src/pages/Batches/SampleDetail.test.tsx`. If `fireEvent` isn't in that import list, add it: `import { fireEvent, screen, waitFor, within } from '@testing-library/react'`.

- [ ] **Step 4: Run the full SampleDetail test file**

Run: `cd web && pnpm exec vitest run src/pages/Batches/SampleDetail.test.tsx`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Lint and typecheck**

Run: `cd web && pnpm lint && pnpm exec tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Batches/SampleDetail.tsx web/src/pages/Batches/SampleDetail.test.tsx
git commit -m "feat(web): replace SampleDetail's screenshot strip + action log table with the replay timeline"
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

Open a `gui_android` or `gui_pc_web` sample's detail page. Confirm: the 截图 card shows one big image + a slider with colored marks below it; dragging/clicking the slider changes the image; selecting an action mark shows its target + success/failure; a sample with no `action_log` still shows a working screenshot-only slider.

- [ ] **Step 4: Update CLAUDE.md**

Add a dated bullet to the "Development status" section (follow the exact style of the adjacent entries — what changed, why, root file names) describing: `SampleDetail`'s screenshot strip + action-log table replaced by `SampleReplayTimeline` (`web/src/components/SampleReplayTimeline.tsx`, merge logic in `web/src/utils/replayTimeline.ts`), scoped to `gui_pc_web`/`gui_android` for now (`agent_pc`/`agent_android`'s differently-shaped `action_log` is a follow-up).

- [ ] **Step 5: Commit the CLAUDE.md update**

```bash
git add CLAUDE.md
git commit -m "docs: log the sample replay timeline feature"
```
