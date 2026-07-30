import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { client } from '../api/client'
import { renderWithProviders } from '../test/test-utils'
import { SystemUpdatePanel } from './SystemUpdatePanel'

const STATUS = {
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
}

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

  it('fails closed (buttons disabled) and shows an error when the status fetch itself fails', async () => {
    // Regression: status.isError was never checked, and `disabled` defaulted
    // to `false` when status was unavailable — check/apply buttons stayed
    // clickable and the version tag just showed "未知" as if that were a
    // normal, safe state instead of "we don't actually know what's going on".
    vi.spyOn(client, 'get').mockRejectedValue(new Error('network down'))
    renderWithProviders(<SystemUpdatePanel />)

    await waitFor(() =>
      expect(screen.getByText('状态加载失败,版本/更新信息不可靠')).toBeInTheDocument(),
    )
    expect(screen.getByText('network down')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '检查更新' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '应用并重启' })).toBeDisabled()
    expect(screen.queryByText(/自更新当前未启用/)).not.toBeInTheDocument()
  })

  it('runs preflight and shows the checklist with a failure surfaced', async () => {
    // URL-aware mock: /status returns status, /preflight returns a failing report.
    vi.spyOn(client, 'get').mockImplementation((url: string) => {
      if (url.includes('preflight')) {
        return Promise.resolve({
          data: {
            ok: false,
            tools: [
              { name: 'git', ok: true, detail: 'git 2.4' },
              { name: 'uv', ok: false, detail: 'not found on PATH' },
              { name: 'pnpm', ok: true, detail: 'pnpm 9' },
            ],
            remote_ok: true,
            remote_detail: 'deadbeef',
            tree_clean: true,
            tree_detail: 'clean',
          },
        }) as never
      }
      return Promise.resolve({ data: STATUS }) as never
    })
    renderWithProviders(<SystemUpdatePanel />)
    await userEvent.click(screen.getByRole('button', { name: '环境自检' }))
    await waitFor(() =>
      expect(screen.getByText('存在问题,更新会中止')).toBeInTheDocument(),
    )
    expect(screen.getByText('not found on PATH')).toBeInTheDocument()
    expect(screen.getByText('远端可拉取')).toBeInTheDocument()
  })
})
