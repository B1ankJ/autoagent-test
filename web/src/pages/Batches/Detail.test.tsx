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
    // rows shown. Sample ids only ever render in the table's ID column
    // (never inside the cluster panel itself), so no table-role scoping
    // is needed to disambiguate.
    expect(screen.getByText('s2')).toBeInTheDocument()
    expect(screen.getByText('s3')).toBeInTheDocument()
    expect(screen.queryByText('s1')).not.toBeInTheDocument()
  })

  it('shows a warning banner when the SSE stream reports the batch is gone (streamGone)', async () => {
    // Regression: useBatchStream's streamGone flag existed with no visible
    // consequence anywhere — a batch deleted while its detail page was open
    // just silently stopped updating, looking indistinguishable from a
    // batch still being live-tracked normally.
    const refetch = vi.fn()
    useBatchStream.mockReturnValue({
      data: {
        batch_id: 'b1',
        name: 'Test',
        mode: 'api',
        status: 'running',
        total: 3,
        done: 1,
        failed: 0,
        concurrency: 1,
        samples: [],
        seq: 4,
      },
      isLoading: false,
      streamGone: true,
      refetch,
    })
    useCancelBatch.mockReturnValue({ mutateAsync: vi.fn() })
    useReplayBatch.mockReturnValue({ mutateAsync: vi.fn(), isPending: false })

    renderWithProviders(
      <Routes>
        <Route path="/batches/:id" element={<BatchDetail />} />
      </Routes>,
      { initialPath: '/batches/b1' },
    )

    expect(await screen.findByText('该批次可能已被删除或清理')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /刷\s?新/ }))
    expect(refetch).toHaveBeenCalled()
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
