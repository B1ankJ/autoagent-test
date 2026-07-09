import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { client } from '../api/client'
import { renderWithProviders } from '../test/test-utils'
import { SystemUpdatePanel } from './SystemUpdatePanel'

function mockStatus(overrides: Record<string, unknown>) {
  vi.spyOn(client, 'get').mockResolvedValue({
    data: {
      enabled: true,
      current_commit: 'aaaaaaaa11',
      current_short: 'aaaaaaaa',
      remote_commit: 'bbbbbbbb22',
      remote_short: 'bbbbbbbb',
      behind: 0,
      up_to_date: true,
      changelog: [],
      fetch_ok: true,
      error: null,
      ...overrides,
    },
  } as never)
}

describe('SystemUpdatePanel', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a disabled notice when self-update is off', async () => {
    mockStatus({ enabled: false })
    renderWithProviders(<SystemUpdatePanel />)
    await waitFor(() =>
      expect(screen.getByText(/自更新当前未启用/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: '检查更新' })).toBeDisabled()
  })

  it('renders behind count and changelog when an update is available', async () => {
    mockStatus({
      up_to_date: false,
      behind: 2,
      changelog: ['abc123 feat: a', 'def456 fix: b'],
    })
    renderWithProviders(<SystemUpdatePanel />)
    await waitFor(() => expect(screen.getByText(/落后 2 个提交/)).toBeInTheDocument())
    expect(screen.getByText('abc123 feat: a')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '应用并重启' })).toBeEnabled()
  })
})
