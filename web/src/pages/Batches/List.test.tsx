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

vi.mock('../../api/batches', () => ({
  useBatches: () => ({ data: [batch], isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  useBatchStats: () => ({
    data: { total: 1, queued: 0, running: 0, done: 1, failed: 0, cancelled: 0 },
  }),
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
