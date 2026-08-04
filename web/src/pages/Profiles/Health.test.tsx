import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { ProfileHealth } from '../../types/api'
import { Health } from './Health'

const useProfileHealth = vi.fn()
const useProfileTrends = vi.fn(() => ({ data: {} }))

vi.mock('../../api/profileHealth', async () => {
  const actual =
    await vi.importActual<typeof import('../../api/profileHealth')>('../../api/profileHealth')
  return {
    ...actual,
    useProfileHealth: () => useProfileHealth(),
    useProfileTrends: () => useProfileTrends(),
  }
})

// Stub the lazy recharts components so the page test doesn't pull in recharts
// (which renders nothing in jsdom anyway).
vi.mock('../../components/ProfileSparkline', () => ({
  __esModule: true,
  ProfileSparkline: () => <div data-testid="sparkline" />,
  default: () => <div data-testid="sparkline" />,
}))
vi.mock('../../components/ProfileTrendModal', () => ({
  __esModule: true,
  ProfileTrendModal: ({ profileName }: { profileName: string | null }) =>
    profileName ? <div>trend-modal:{profileName}</div> : null,
  default: ({ profileName }: { profileName: string | null }) =>
    profileName ? <div>trend-modal:{profileName}</div> : null,
}))

// Stub the device-screens modal (it pulls in websocket/video-decoder
// internals covered by its own test) — assert only that Health opens it with
// the right props.
vi.mock('../../components/ProfileDeviceScreensModal', () => ({
  ProfileDeviceScreensModal: ({
    profileName,
    serials,
  }: {
    profileName: string | null
    serials: string[]
  }) =>
    profileName ? (
      <div>
        device-modal:{profileName}:{serials.join(',')}
      </div>
    ) : null,
}))

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
    serials: [],
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
    useProfileTrends.mockReturnValue({ data: {} })
  })

  it('opens the trend modal when a card body is clicked', async () => {
    useProfileHealth.mockReturnValue({
      data: [row({ name: 'trendp', status: 'green' })],
      isLoading: false,
      isError: false,
    })
    useProfileTrends.mockReturnValue({ data: { trendp: [] } })

    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    // Click the platform tag inside the card body (the profile name is a
    // stopPropagation link, so clicking it would navigate instead of opening
    // the trend modal).
    await userEvent.click(await screen.findByText('api'))
    expect(await screen.findByText('trend-modal:trendp')).toBeInTheDocument()
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

  it('opens the device-screens modal scoped to the profile serials when the device count is clicked', async () => {
    useProfileHealth.mockReturnValue({
      data: [
        row({
          name: 'droid',
          platform: 'android',
          status: 'yellow',
          devices_online: 1,
          devices_total: 2,
          serials: ['dev1', 'dev2'],
        }),
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
    await userEvent.click(await screen.findByText(/设备 1\/2/))
    expect(await screen.findByText('device-modal:droid:dev1,dev2')).toBeInTheDocument()
  })

  it('renders the device count as plain text (not clickable) for non-android profiles', async () => {
    useProfileHealth.mockReturnValue({
      data: [row({ name: 'apip', platform: 'api', devices_online: null, devices_total: null })],
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/profiles/health" element={<Health />} />
      </Routes>,
      { initialPath: '/profiles/health' },
    )
    await waitFor(() => expect(screen.getByText(/设备 —/)).toBeInTheDocument())
  })
})
