import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { BatchDetail } from '../../types/api'
import { Compare } from './Compare'

const useBatch = vi.fn()

vi.mock('../../api/batches', () => ({
  useBatch: (...args: unknown[]) => useBatch(...args),
}))

function batch(overrides: Partial<BatchDetail>): BatchDetail {
  return {
    batch_id: 'b',
    name: 'Batch',
    mode: 'api',
    status: 'done',
    total: 0,
    done: 0,
    failed: 0,
    concurrency: 1,
    seq: 1,
    samples: [],
    ...overrides,
  }
}

function mockBatches(a: BatchDetail, b: BatchDetail) {
  useBatch.mockImplementation((id: string | undefined) => {
    if (id === a.batch_id) return { data: a, isLoading: false, isError: false, error: null }
    if (id === b.batch_id) return { data: b, isLoading: false, isError: false, error: null }
    return { data: undefined, isLoading: false, isError: false, error: null }
  })
}

function renderCompare(search: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/batches/compare" element={<Compare />} />
    </Routes>,
    { initialPath: `/batches/compare${search}` },
  )
}

describe('Compare', () => {
  afterEach(() => {
    useBatch.mockReset()
  })

  it('shows the summary counts and matched/unmatched rows', async () => {
    mockBatches(
      batch({
        batch_id: 'b1',
        name: 'Run A',
        samples: [
          {
            id: 's1',
            prompts: ['x'],
            mode: 'api',
            target_profile: 'p',
            responses: ['hello world'],
            duration_ms: 100,
          },
          {
            id: 'only-a',
            prompts: ['x'],
            mode: 'api',
            target_profile: 'p',
            responses: ['x'],
            duration_ms: 50,
          },
        ],
      }),
      batch({
        batch_id: 'b2',
        name: 'Run B',
        samples: [
          {
            id: 's1',
            prompts: ['x'],
            mode: 'api',
            target_profile: 'p',
            responses: ['hello there'],
            duration_ms: 130,
          },
        ],
      }),
    )

    renderCompare('?a=b1&b=b2')

    await waitFor(() => expect(screen.getByText('Run A')).toBeInTheDocument())
    expect(screen.getByText('Run B')).toBeInTheDocument()
    // Summary: 1 common, 1 only-A, 0 only-B.
    expect(screen.getByText(/1 个共同 sample/)).toBeInTheDocument()
    expect(screen.getByText(/1 个仅 A/)).toBeInTheDocument()
    expect(screen.getByText(/0 个仅 B/)).toBeInTheDocument()

    // Both rows render by id.
    expect(screen.getByText('s1')).toBeInTheDocument()
    expect(screen.getByText('only-a')).toBeInTheDocument()
    // The only-A row is flagged as one-sided.
    expect(screen.getByText('仅 A 存在')).toBeInTheDocument()
  })

  it('shows the word-level diff when a matched row is expanded', async () => {
    mockBatches(
      batch({
        batch_id: 'b1',
        name: 'Run A',
        samples: [
          {
            id: 's1',
            prompts: ['x'],
            mode: 'api',
            target_profile: 'p',
            responses: ['hello world'],
            duration_ms: 100,
          },
        ],
      }),
      batch({
        batch_id: 'b2',
        name: 'Run B',
        samples: [
          {
            id: 's1',
            prompts: ['x'],
            mode: 'api',
            target_profile: 'p',
            responses: ['hello there'],
            duration_ms: 130,
          },
        ],
      }),
    )

    const { container } = renderCompare('?a=b1&b=b2')
    await waitFor(() => expect(screen.getByText('s1')).toBeInTheDocument())

    const expandIcon = container.querySelector('.ant-table-row-expand-icon')
    expect(expandIcon).not.toBeNull()
    await userEvent.click(expandIcon as HTMLElement)

    await waitFor(() => {
      expect(screen.getByText('world')).toBeInTheDocument()
      expect(screen.getByText('there')).toBeInTheDocument()
    })
  })

  it('shows an error state when a batch fails to load', async () => {
    useBatch.mockImplementation((id: string | undefined) => {
      if (id === 'b1') {
        return { data: undefined, isLoading: false, isError: true, error: new Error('boom') }
      }
      return {
        data: batch({ batch_id: 'b2', name: 'Run B' }),
        isLoading: false,
        isError: false,
        error: null,
      }
    })

    renderCompare('?a=b1&b=b2')
    await waitFor(() => expect(screen.getByText(/加载失败/)).toBeInTheDocument())
  })

  it('shows an error state when a or b is missing from the query string', async () => {
    useBatch.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null })
    renderCompare('?a=b1')
    expect(await screen.findByText(/需要选择两个批次/)).toBeInTheDocument()
  })
})
