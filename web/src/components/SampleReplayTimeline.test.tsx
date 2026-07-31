import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  renderWithClient(<SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={undefined} />)
  expect(await screen.findByText('暂无截图')).toBeInTheDocument()
})

it('renders screenshot-only marks when there is no action_log (fallback mode)', async () => {
  listScreenshots.mockResolvedValue(SCREENSHOTS)
  renderWithClient(<SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={undefined} />)
  await waitFor(() => expect(screen.getAllByRole('slider')).toHaveLength(1))
  expect(screen.getByRole('img')).toHaveAttribute(
    'src',
    '/api/v1/media/batches/b1/samples/s1/screenshot/done.jpg',
  )
})

it('defaults to the last event and lets keyboard arrows scrub backward through actions', async () => {
  listScreenshots.mockResolvedValue(SCREENSHOTS)
  renderWithClient(<SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={ACTION_LOG} />)

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
  act(() => fireEvent.keyDown(handle, { key: 'ArrowLeft', keyCode: 37, which: 37 }))
  expect(await screen.findByText('xpath://*[@text="发送"]')).toBeInTheDocument()
  expect(screen.getByText('element not found')).toBeInTheDocument()

  act(() => fireEvent.keyDown(handle, { key: 'ArrowLeft', keyCode: 37, which: 37 }))
  expect(await screen.findByText('(495, 2059)')).toBeInTheDocument()
})

it('shows a retry button when the screenshot list fails to load', async () => {
  listScreenshots.mockRejectedValue(new Error('boom'))
  renderWithClient(<SampleReplayTimeline batchId="b1" sampleId="s1" actionLog={undefined} />)
  expect(await screen.findByText('截图加载失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /重\s?试/ })).toBeInTheDocument()
})
