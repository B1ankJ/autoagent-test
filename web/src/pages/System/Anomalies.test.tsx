import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { AnomalyRecord } from '../../types/api'
import { Anomalies } from './Anomalies'

const useAnomalies = vi.fn()
const acknowledgeMutate = vi.fn()

vi.mock('../../api/anomalies', () => ({
  useAnomalies: (...a: unknown[]) => useAnomalies(...a),
  useAcknowledgeAnomaly: () => ({ mutateAsync: acknowledgeMutate, isPending: false }),
  buildAnomalyParams: () => ({}),
}))

function rec(over: Partial<AnomalyRecord> & { id: number }): AnomalyRecord {
  return {
    type: 'duration',
    batch_id: 'b1',
    sample_id: 's1',
    target_profile: 'p1',
    summary: '耗时异常',
    detail: {},
    acknowledged: false,
    created_at: '2026-08-03T00:00:00Z',
    ...over,
  }
}

function SampleStub() {
  const loc = useLocation()
  return <div>sample-page{loc.pathname}</div>
}

describe('Anomalies', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders rows and acknowledges one', async () => {
    useAnomalies.mockReturnValue({
      data: { items: [rec({ id: 1, summary: '慢了' })], total: 1 },
      isLoading: false,
      isError: false,
    })
    acknowledgeMutate.mockResolvedValue({})

    renderWithProviders(
      <Routes>
        <Route path="/system/anomalies" element={<Anomalies />} />
        <Route path="/batches/:id/samples/:sid" element={<SampleStub />} />
      </Routes>,
      { initialPath: '/system/anomalies' },
    )

    await waitFor(() => expect(screen.getByText('慢了')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /确\s?认/ }))
    await waitFor(() => expect(acknowledgeMutate).toHaveBeenCalledWith(1))
  })

  it('links a row through to its sample detail', async () => {
    useAnomalies.mockReturnValue({
      data: { items: [rec({ id: 2, batch_id: 'bb', sample_id: 'ss' })], total: 1 },
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/system/anomalies" element={<Anomalies />} />
        <Route path="/batches/:id/samples/:sid" element={<SampleStub />} />
      </Routes>,
      { initialPath: '/system/anomalies' },
    )
    await userEvent.click(await screen.findByText('查看'))
    expect(await screen.findByText('sample-page/batches/bb/samples/ss')).toBeInTheDocument()
  })

  it('prefills the profile filter from the URL target_profile query', async () => {
    useAnomalies.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/system/anomalies" element={<Anomalies />} />
      </Routes>,
      { initialPath: '/system/anomalies?target_profile=qwen' },
    )
    await waitFor(() => {
      const calledWith = useAnomalies.mock.calls.at(-1)?.[0]
      expect(calledWith).toMatchObject({ target_profile: 'qwen' })
    })
  })
})
