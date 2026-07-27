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
    const table = screen.getByRole('table')
    expect(within(table).getByText('模式')).toBeInTheDocument()
    expect(within(table).getByText('开始时间')).toBeInTheDocument()
  })

  it('hides a column via the 列 popover and remembers the choice', async () => {
    renderWithProviders(<BatchList />)
    await waitFor(() => expect(screen.getByText('nightly regression')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /列/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: '模式' }))

    const table = screen.getByRole('table')
    expect(within(table).queryByText('模式')).not.toBeInTheDocument()
    // Other toggleable columns stay visible — only the unchecked one is gone.
    expect(within(table).getByText('开始时间')).toBeInTheDocument()

    const saved = JSON.parse(localStorage.getItem(COLUMN_VISIBILITY_KEY) ?? '[]') as string[]
    expect(saved).not.toContain('mode')
    expect(saved).toContain('started_at')
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
        expect.objectContaining({ status: 'failed', mode: 'gui_android' }),
      )
      expect(mockUseBatchStats).toHaveBeenLastCalledWith(
        expect.objectContaining({ mode: 'gui_android' }),
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
