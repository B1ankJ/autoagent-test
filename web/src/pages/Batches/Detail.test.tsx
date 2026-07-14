import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import { BatchDetail } from './Detail'

const useBatchStream = vi.fn()
const useCancelBatch = vi.fn()
const useReplayBatch = vi.fn()

vi.mock('../../api/batches', async () => {
  const actual = await vi.importActual<typeof import('../../api/batches')>('../../api/batches')
  return {
    ...actual,
    useCancelBatch: () => useCancelBatch(),
    useReplayBatch: () => useReplayBatch(),
    statusIsTerminal: actual.statusIsTerminal,
    useBatchStream: (...args: unknown[]) => useBatchStream(...args),
  }
})

describe('BatchDetail', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    useBatchStream.mockReset()
    useCancelBatch.mockReset()
    useReplayBatch.mockReset()
  })

  it('renders batch info from stream hook', async () => {
    useBatchStream.mockReturnValue({
      data: {
        batch_id: 'b1',
        name: 'Test',
        mode: 'api',
        status: 'done',
        total: 3,
        done: 3,
        failed: 0,
        concurrency: 1,
        samples: [],
        seq: 4,
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

    await waitFor(() => {
      expect(screen.getByText('Test')).toBeInTheDocument()
    })
    expect(useBatchStream).toHaveBeenCalledWith('b1')
    expect(screen.getByText('done')).toBeInTheDocument()
    expect(screen.getByText('3 / 3')).toBeInTheDocument()
    expect(screen.getByText(/done 3 · failed 0/)).toBeInTheDocument()
  })

  it('replays the batch with identical config via the dropdown menu', async () => {
    useBatchStream.mockReturnValue({
      data: {
        batch_id: 'b1',
        name: 'Test',
        mode: 'api',
        status: 'done',
        total: 3,
        done: 2,
        failed: 1,
        concurrency: 1,
        samples: [],
        seq: 4,
      },
      isLoading: false,
    })
    useCancelBatch.mockReturnValue({ mutateAsync: vi.fn() })
    const replayMutateAsync = vi.fn().mockResolvedValue({ batch_id: 'b2' })
    useReplayBatch.mockReturnValue({ mutateAsync: replayMutateAsync, isPending: false })

    const { container } = renderWithProviders(
      <Routes>
        <Route path="/batches/:id" element={<BatchDetail />} />
      </Routes>,
      { initialPath: '/batches/b1' },
    )
    await waitFor(() => expect(screen.getByText('Test')).toBeInTheDocument())

    // Dropdown.Button's caret (an icon-only second button) opens the menu;
    // the main button click area triggers "重跑失败" instead.
    const caret = container.querySelector<HTMLButtonElement>(
      '.ant-dropdown-button .ant-btn-icon-only',
    )
    expect(caret).not.toBeNull()
    await userEvent.click(caret as HTMLButtonElement)
    await userEvent.click(await screen.findByText('完整重放(与原批次配置完全一致)'))

    await waitFor(() => expect(replayMutateAsync).toHaveBeenCalledWith('b1'))
  })
})
