import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { Dashboard } from './Dashboard'

const { statsMock, profilesMock, vlmMock, useBatchesMock } = vi.hoisted(() => ({
  statsMock: vi.fn(),
  profilesMock: vi.fn(),
  vlmMock: vi.fn(),
  useBatchesMock: vi.fn((_params?: unknown) => ({ data: [] as unknown[] })),
}))

vi.mock('../api/batches', () => ({
  useBatches: useBatchesMock,
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

describe('Dashboard 进行中/排队中 panel', () => {
  afterEach(() => {
    vi.clearAllMocks()
    useBatchesMock.mockReturnValue({ data: [] })
  })

  it('fetches running and queued batches via separate status-filtered queries', async () => {
    statsMock.mockReturnValue({ total: 5, queued: 1, running: 2, done: 2, failed: 0, cancelled: 0 })
    profilesMock.mockReturnValue([])
    vlmMock.mockReturnValue(null)

    renderWithProviders(<Dashboard />)
    await waitFor(() => expect(screen.getByText('Dashboard')).toBeInTheDocument())

    expect(useBatchesMock).toHaveBeenCalledWith(expect.objectContaining({ status: 'running' }))
    expect(useBatchesMock).toHaveBeenCalledWith(expect.objectContaining({ status: 'queued' }))
  })

  it('shows the accurate active count from stats even when the panel can only display a capped number of rows', async () => {
    statsMock.mockReturnValue({
      total: 20,
      queued: 5,
      running: 10,
      done: 5,
      failed: 0,
      cancelled: 0,
    })
    profilesMock.mockReturnValue([])
    vlmMock.mockReturnValue(null)
    useBatchesMock.mockImplementation((raw?: unknown) => {
      const params = raw as { status: string }
      return {
        data: Array.from({ length: 6 }, (_, i) => ({
          batch_id: `${params.status}-${i}`,
          name: `${params.status} batch ${i}`,
          mode: 'api',
          status: params.status,
          total: 1,
          done: 0,
          failed: 0,
        })),
      }
    })

    renderWithProviders(<Dashboard />)

    // stats says 15 active (10 running + 5 queued) — the true count — even
    // though each status-filtered fetch is capped and the panel only has
    // room to render 8 rows.
    expect(await screen.findByText('15 个')).toBeInTheDocument()
    expect(screen.getByText(/查看全部 \(还有 7 个\)/)).toBeInTheDocument()
  })
})
