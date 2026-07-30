import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../../test/test-utils'
import { BatchSummary } from '../../types/api'
import { BatchList } from './List'

const batch: BatchSummary = {
  batch_id: 'b1',
  name: 'nightly regression',
  mode: 'api',
  status: 'done',
  total: 1,
  done: 1,
  failed: 0,
  started_at: '2026-04-22T00:00:00Z',
  profiles: ['p1'],
  devices: [],
}

const { mockUseBatches, mockUseBatchStats, mockUseSessionConversation } = vi.hoisted(() => ({
  mockUseBatches: vi.fn(),
  mockUseBatchStats: vi.fn(),
  mockUseSessionConversation: vi.fn(),
}))

vi.mock('../../api/batches', () => ({
  useBatches: mockUseBatches,
  useBatchStats: mockUseBatchStats,
  useSessionConversation: mockUseSessionConversation,
  useBatch: () => ({ data: undefined, isLoading: false, error: null }),
  useCancelActiveBatches: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useCancelBatch: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useDeleteBatch: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useDeleteBatchesByStatus: () => ({ isPending: false, mutateAsync: vi.fn() }),
}))

vi.mock('../../api/profiles', () => ({
  useProfiles: () => ({ data: [], isLoading: false }),
}))

vi.mock('../../api/devices', () => ({
  useDevices: () => ({ data: [], isLoading: false }),
}))

vi.mock('../../api/deviceStream', () => {
  const stubHandle = {
    canvasRef: { current: null },
    state: 'closed' as const,
    latencyMs: null,
    reconnect: vi.fn(),
  }
  return {
    useDeviceHttpStream: () => stubHandle,
    postDeviceInput: vi.fn(),
  }
})

const COLUMN_VISIBILITY_KEY = 'autoagent_batches_visible_columns'

describe('BatchList column visibility', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseBatches.mockReturnValue({
      data: [batch],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockUseBatchStats.mockReturnValue({
      data: { total: 1, queued: 0, running: 0, done: 1, failed: 0, cancelled: 0 },
    })
    mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows all toggleable columns by default', async () => {
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())
    // Scoped to <thead>: rc-table also renders a hidden aria-hidden
    // "measure row" mirroring column titles (used to compute pixel widths
    // for horizontal-scroll tables), which would otherwise double-match.
    const thead = screen.getByRole('table').querySelector('thead')!
    expect(within(thead).getByText('模式')).toBeInTheDocument()
    expect(within(thead).getByText('开始时间')).toBeInTheDocument()
  })

  it('hides a column via the 列 popover and remembers the choice', async () => {
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /列/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: '模式' }))

    const thead = screen.getByRole('table').querySelector('thead')!
    expect(within(thead).queryByText('模式')).not.toBeInTheDocument()
    // Other toggleable columns stay visible — only the unchecked one is gone.
    expect(within(thead).getByText('开始时间')).toBeInTheDocument()

    const saved = JSON.parse(localStorage.getItem(COLUMN_VISIBILITY_KEY) ?? '[]') as string[]
    expect(saved).not.toContain('mode')
    expect(saved).toContain('started_at')
  })

  it('opens the device stream modal when clicking a device chip in the Profile/设备 column', async () => {
    const user = userEvent.setup()
    mockUseBatches.mockReturnValue({
      data: [{ ...batch, devices: ['dev-1'] }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    await user.click(screen.getByText('dev-1'))
    expect(await screen.findByRole('dialog')).toHaveTextContent('dev-1')
  })

  it('shows the effective response for a single-sample batch and "-" for multi-sample ones', async () => {
    mockUseBatches.mockReturnValue({
      data: [
        { ...batch, batch_id: 'b1', name: 'single sample run', total: 1, preview_response: 'llm-reviewed answer' },
        { ...batch, batch_id: 'b2', name: 'multi sample run', total: 3, preview_response: null },
      ],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('single sample run')).toBeInTheDocument())

    const table = screen.getByRole('table')
    expect(within(table).getByText('llm-reviewed answer')).toBeInTheDocument()
    expect(within(table).getAllByText('-').length).toBeGreaterThan(0)
  })

  it('does not open a modal when clicking a profile chip', async () => {
    const user = userEvent.setup()
    mockUseBatches.mockReturnValue({
      data: [{ ...batch, devices: ['dev-1'] }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    await user.click(screen.getByText('p1'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('BatchList status/mode filters', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseBatches.mockReturnValue({
      data: [batch],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockUseBatchStats.mockReturnValue({
      data: { total: 5, queued: 0, running: 0, done: 3, failed: 2, cancelled: 0 },
    })
    mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('sends status/mode from the URL to the backend queries instead of only filtering the fetched page client-side', async () => {
    renderWithProviders(<BatchList />, { initialPath: '/batches?status=failed&mode=gui_android' })

    // Regression: status/mode used to be parsed from the URL but only ever
    // applied to `data` after the fact via Array.filter — since `data` is
    // just one paginated page from the backend, a status with no matches on
    // that page rendered an empty table even when matching batches existed
    // elsewhere. They must reach the backend queries as real params.
    await waitFor(() => {
      expect(mockUseBatches).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: ['failed'], mode: ['gui_android'] }),
      )
      expect(mockUseBatchStats).toHaveBeenLastCalledWith(
        expect.objectContaining({ mode: ['gui_android'] }),
      )
    })
  })

  it('supports selecting multiple statuses/modes at once via comma-joined URL params', async () => {
    renderWithProviders(<BatchList />, {
      initialPath: '/batches?status=failed,done&mode=gui_android,api',
    })

    await waitFor(() => {
      expect(mockUseBatches).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: ['failed', 'done'], mode: ['gui_android', 'api'] }),
      )
    })
  })

  it('paginates against the filtered count, not the grand total, when a status filter is active', async () => {
    // /batches/stats groups by status rather than accepting one, so with
    // status=failed active the pagination total must come from stats.failed
    // (2), not stats.total (5) — otherwise the "共 N 条" count and page
    // controls stay sized for every status combined.
    renderWithProviders(<BatchList />, { initialPath: '/batches?status=failed' })

    await waitFor(() => expect(screen.getByText('共 2 条')).toBeInTheDocument())
    expect(screen.queryByText('共 5 条')).not.toBeInTheDocument()
  })
})

describe('BatchList multi-turn conversation link', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseBatchStats.mockReturnValue({
      data: { total: 1, queued: 0, running: 0, done: 1, failed: 0, cancelled: 0 },
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows no 多轮对话 tag when the batch has no session_id', async () => {
    mockUseBatches.mockReturnValue({
      data: [batch],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())
    expect(screen.queryByText('多轮对话')).not.toBeInTheDocument()
  })

  it('opens the conversation modal for a batch whose sample carries a session_id', async () => {
    const user = userEvent.setup()
    mockUseBatches.mockReturnValue({
      data: [{ ...batch, session_id: 'conv-1' }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    mockUseSessionConversation.mockReturnValue({
      data: [
        { batch_id: 'b1', sample_id: 's1', status: 'done', prompt: 'hi', response: 'hello!' },
      ],
      isLoading: false,
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    await user.click(screen.getByText('多轮对话'))

    expect(await screen.findByText('第 1 轮')).toBeInTheDocument()
    expect(mockUseSessionConversation).toHaveBeenCalledWith('conv-1')
  })
})

describe('BatchList end_session tag and filter', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseBatchStats.mockReturnValue({
      data: { total: 1, queued: 0, running: 0, done: 1, failed: 0, cancelled: 0 },
    })
    mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows a 结束会话 tag for a batch whose sample was an end_session no-op', async () => {
    mockUseBatches.mockReturnValue({
      data: [{ ...batch, is_end_session: true }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())
    expect(screen.getByText('结束会话')).toBeInTheDocument()
  })

  it('does not show the tag for a normal batch', async () => {
    mockUseBatches.mockReturnValue({
      data: [batch],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())
    expect(screen.queryByText('结束会话')).not.toBeInTheDocument()
  })

  it('sends exclude_end_session to the backend when the URL hides end_session records', async () => {
    mockUseBatches.mockReturnValue({
      data: [batch],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />, { initialPath: '/batches?hide_end_session=1' })

    await waitFor(() => {
      expect(mockUseBatches).toHaveBeenLastCalledWith(
        expect.objectContaining({ excludeEndSession: true }),
      )
      expect(mockUseBatchStats).toHaveBeenLastCalledWith(
        expect.objectContaining({ excludeEndSession: true }),
      )
    })
    expect(screen.getByText('已隐藏结束会话记录')).toBeInTheDocument()
  })
})

describe('BatchList duration column and anomaly filter', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseBatchStats.mockReturnValue({
      data: { total: 1, queued: 0, running: 0, done: 1, failed: 0, cancelled: 0 },
    })
    mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows the formatted duration and highlights an anomalous one in red', async () => {
    mockUseBatches.mockReturnValue({
      data: [{ ...batch, avg_duration_ms: 5000, is_duration_anomaly: true }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    const durationCell = screen.getByText('5.0s')
    expect(durationCell).toHaveStyle({ color: 'var(--aa-red, #cf1322)' })
  })

  it('shows a plain (non-highlighted) duration for a normal batch', async () => {
    mockUseBatches.mockReturnValue({
      data: [{ ...batch, avg_duration_ms: 500, is_duration_anomaly: false }],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    const durationCell = screen.getByText('500ms')
    expect(durationCell.style.color).toBe('')
  })

  it('sends duration_anomaly_only to the backend when the URL enables it', async () => {
    mockUseBatches.mockReturnValue({
      data: [batch],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    })
    renderWithProviders(<BatchList />, { initialPath: '/batches?duration_anomaly=1' })

    await waitFor(() => {
      expect(mockUseBatches).toHaveBeenLastCalledWith(
        expect.objectContaining({ durationAnomalyOnly: true }),
      )
      expect(mockUseBatchStats).toHaveBeenLastCalledWith(
        expect.objectContaining({ durationAnomalyOnly: true }),
      )
    })
    expect(screen.getByText('仅耗时异常')).toBeInTheDocument()
  })
})
