import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { Dashboard } from './Dashboard'

const { statsMock, profilesMock, vlmMock } = vi.hoisted(() => ({
  statsMock: vi.fn(),
  profilesMock: vi.fn(),
  vlmMock: vi.fn(),
}))

vi.mock('../api/batches', () => ({
  useBatches: () => ({ data: [] }),
  useBatchStats: () => ({ data: statsMock() }),
}))

vi.mock('../api/profiles', () => ({
  useProfiles: () => ({ data: profilesMock() }),
}))

vi.mock('../api/config', () => ({
  useVLM: () => ({ data: vlmMock() }),
}))

describe('Dashboard onboarding checklist', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows the checklist with all steps pending on a fresh install', async () => {
    statsMock.mockReturnValue({ total: 0, queued: 0, running: 0, done: 0, failed: 0, cancelled: 0 })
    profilesMock.mockReturnValue([])
    vlmMock.mockReturnValue(null)

    renderWithProviders(<Dashboard />)

    await waitFor(() => expect(screen.getByText('上手清单')).toBeInTheDocument())
    expect(screen.getByText('配置 VLM(可选)')).toBeInTheDocument()
    expect(screen.getByText('创建 Profile')).toBeInTheDocument()
    expect(screen.getByText('跑第一个批次')).toBeInTheDocument()
    // Every step still pending → each shows a "去完成" link.
    expect(screen.getAllByText(/去完成/)).toHaveLength(3)
  })

  it('marks steps done as the user configures VLM and profiles', async () => {
    statsMock.mockReturnValue({ total: 0, queued: 0, running: 0, done: 0, failed: 0, cancelled: 0 })
    profilesMock.mockReturnValue([{ name: 'p1', platform: 'android' }])
    vlmMock.mockReturnValue({ base_url: 'https://x', model: 'm', api_key: 'k' })

    renderWithProviders(<Dashboard />)

    await waitFor(() => expect(screen.getByText('上手清单')).toBeInTheDocument())
    // Only the still-incomplete step ("跑第一个批次") should offer 去完成.
    expect(screen.getAllByText(/去完成/)).toHaveLength(1)
  })

  it('hides the checklist once at least one batch has run', async () => {
    statsMock.mockReturnValue({ total: 3, queued: 0, running: 0, done: 3, failed: 0, cancelled: 0 })
    profilesMock.mockReturnValue([])
    vlmMock.mockReturnValue(null)

    renderWithProviders(<Dashboard />)

    await waitFor(() => expect(screen.getByText('Dashboard')).toBeInTheDocument())
    expect(screen.queryByText('上手清单')).not.toBeInTheDocument()
  })
})
