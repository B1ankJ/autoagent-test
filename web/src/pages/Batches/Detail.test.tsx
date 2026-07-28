import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import { BatchDetail } from './Detail'

function BatchesListStub() {
  const location = useLocation()
  return <div>batches-list-page{location.search}</div>
}

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

  it('keeps the dropdown caret usable even when there are no failed samples', async () => {
    // Regression: a top-level `disabled` on Dropdown.Button used to grey out
    // the caret too, making 重跑全部/完整重放 unreachable whenever a batch
    // finished with zero failures (the common case).
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
    const replayMutateAsync = vi.fn().mockResolvedValue({ batch_id: 'b2' })
    useReplayBatch.mockReturnValue({ mutateAsync: replayMutateAsync, isPending: false })

    const { container } = renderWithProviders(
      <Routes>
        <Route path="/batches/:id" element={<BatchDetail />} />
      </Routes>,
      { initialPath: '/batches/b1' },
    )
    await waitFor(() => expect(screen.getByText('Test')).toBeInTheDocument())

    const primaryButton = screen.getByRole('button', { name: /重跑失败/i })
    expect(primaryButton).toBeDisabled()

    const caret = container.querySelector<HTMLButtonElement>(
      '.ant-dropdown-button .ant-btn-icon-only',
    )
    expect(caret).not.toBeNull()
    expect(caret).not.toBeDisabled()

    await userEvent.click(caret as HTMLButtonElement)
    await userEvent.click(await screen.findByText('完整重放(与原批次配置完全一致)'))

    await waitFor(() => expect(replayMutateAsync).toHaveBeenCalledWith('b1'))
  })

  it('返回 link restores the Batches List querystring (filters/pagination/search) instead of a bare path', async () => {
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
        <Route path="/batches" element={<BatchesListStub />} />
        <Route path="/batches/:id" element={<BatchDetail />} />
      </Routes>,
      {
        initialEntries: ['/batches?status=failed&page=2', '/batches/b1'],
        initialIndex: 1,
      },
    )
    await waitFor(() => expect(screen.getByText('Test')).toBeInTheDocument())

    await userEvent.click(screen.getByText('批次'))

    expect(
      await screen.findByText('batches-list-page?status=failed&page=2'),
    ).toBeInTheDocument()
  })

  it('falls back to a plain /batches navigation when there is no in-app history to go back to', async () => {
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
        <Route path="/batches" element={<BatchesListStub />} />
        <Route path="/batches/:id" element={<BatchDetail />} />
      </Routes>,
      { initialPath: '/batches/b1' },
    )
    await waitFor(() => expect(screen.getByText('Test')).toBeInTheDocument())

    await userEvent.click(screen.getByText('批次'))

    expect(await screen.findByText('batches-list-page')).toBeInTheDocument()
  })
})
