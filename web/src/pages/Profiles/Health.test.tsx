import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { ProfileHealth } from '../../types/api'
import { Health } from './Health'

const useProfileHealth = vi.fn()

vi.mock('../../api/profileHealth', async () => {
  const actual =
    await vi.importActual<typeof import('../../api/profileHealth')>('../../api/profileHealth')
  return { ...actual, useProfileHealth: () => useProfileHealth() }
})

function row(over: Partial<ProfileHealth> & { name: string }): ProfileHealth {
  return {
    platform: 'api',
    status: 'green',
    success_rate: 1,
    total_runs: 5,
    avg_duration_ms: 100,
    unacked_anomalies: 0,
    devices_online: null,
    devices_total: null,
    ...over,
  }
}

function AnomaliesStub() {
  const loc = useLocation()
  return <div>anomalies-page{loc.search}</div>
}

describe('Health', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders cards worst-first with a summary bar', async () => {
    useProfileHealth.mockReturnValue({
      data: [
        row({ name: 'bad', status: 'red', unacked_anomalies: 6, success_rate: 0.4 }),
        row({ name: 'good', status: 'green' }),
      ],
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    await waitFor(() => expect(screen.getByText('bad')).toBeInTheDocument())
    expect(screen.getByText('good')).toBeInTheDocument()
    expect(screen.getByText(/1 异常/)).toBeInTheDocument()
  })

  it('renders in the API-provided order (no client re-sort that could disagree with the backend)', async () => {
    // Backend returns worst-first; a nodata profile must NOT be hoisted above a
    // green one by any client-side re-sort. Feed a green-before-nodata order and
    // assert it's preserved verbatim.
    useProfileHealth.mockReturnValue({
      data: [
        row({ name: 'alpha', status: 'green' }),
        row({ name: 'zeta', status: 'nodata', success_rate: null, total_runs: 0 }),
      ],
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    await waitFor(() => expect(screen.getByText('alpha')).toBeInTheDocument())
    const names = screen.getAllByText(/alpha|zeta/).map((el) => el.textContent)
    expect(names).toEqual(['alpha', 'zeta'])
  })

  it('clicks the anomaly count through to the anomaly center filtered by profile', async () => {
    useProfileHealth.mockReturnValue({
      data: [row({ name: 'bad', status: 'red', unacked_anomalies: 3 })],
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
        <Route path="/system/anomalies" element={<AnomaliesStub />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    await userEvent.click(await screen.findByText(/异常 3/))
    expect(await screen.findByText('anomalies-page?target_profile=bad')).toBeInTheDocument()
  })
})
