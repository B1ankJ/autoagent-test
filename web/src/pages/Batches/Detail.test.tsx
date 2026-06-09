import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import { BatchDetail } from './Detail'

const useBatchStream = vi.fn()
const useCancelBatch = vi.fn()

vi.mock('../../api/batches', async () => {
  const actual = await vi.importActual<typeof import('../../api/batches')>('../../api/batches')
  return {
    ...actual,
    useCancelBatch: () => useCancelBatch(),
    statusIsTerminal: actual.statusIsTerminal,
    useBatchStream: (...args: unknown[]) => useBatchStream(...args),
  }
})

describe('BatchDetail', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    useBatchStream.mockReset()
    useCancelBatch.mockReset()
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
})
