import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import { ConfigPage } from './Config'

interface WhitelistFixture {
  target_profile: string
  response: string
  response_excerpt: string
  added_at: string
}

const { testLlmMock, backupListMock, deleteBackupMock, downloadBackupMock, whitelistMock } =
  vi.hoisted(() => ({
    testLlmMock: vi.fn(),
    backupListMock: vi.fn(() => ({
      data: [] as { name: string; bytes: number; created_at: string }[],
    })),
    deleteBackupMock: vi.fn(async () => {}),
    downloadBackupMock: vi.fn(async () => {}),
    whitelistMock: vi.fn(() => ({ data: [] as WhitelistFixture[], refetch: vi.fn() })),
  }))

vi.mock('../api/config', () => ({
  useVLM: () => ({ data: { base_url: 'https://old', model: 'old-model', api_key: 'old-key' } }),
  useSaveVLM: () => ({ isPending: false, mutateAsync: vi.fn(async (body) => body) }),
  useTestLLM: () => ({ isPending: false, mutateAsync: testLlmMock }),
  useDefaults: () => ({ data: { api_timeout_sec: 60, gui_timeout_sec: 180, retry: 2, concurrency: 1, verbose_logs: true } }),
  useSaveDefaults: () => ({ isPending: false, mutateAsync: vi.fn(async (body) => body) }),
  useNotifications: () => ({ data: { enabled: false, webhook_url: '', secret: '', empty_response_threshold: 3, empty_response_auto_reinit: false, same_response_enabled: false, same_response_threshold: 3, same_response_auto_reinit: false, anr_check_enabled: false, at_mobiles: [], at_all: false, app_base_url: '' } }),
  useSaveNotifications: () => ({ isPending: false, mutateAsync: vi.fn(async (body) => body) }),
  useTestNotifications: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useWhitelist: whitelistMock,
  useRemoveWhitelist: () => ({ isPending: false, mutateAsync: vi.fn() }),
  usePreviewLogsCleanup: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useRunLogsCleanup: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useBackupList: backupListMock,
  useRunBackup: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useDeleteBackup: () => ({ isPending: false, mutateAsync: deleteBackupMock }),
  downloadBackup: downloadBackupMock,
}))

describe('ConfigPage', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows staged auth error after connectivity test', async () => {
    testLlmMock.mockResolvedValue({
      ok: false,
      stage: 'auth',
      message: 'bad key',
      latency_ms: 5,
    })

    renderWithProviders(<ConfigPage />)

    const inputs = screen.getAllByRole('textbox')
    await userEvent.clear(inputs[0])
    await userEvent.type(inputs[0], 'https://api.example/v1')
    await userEvent.clear(inputs[1])
    await userEvent.type(inputs[1], 'qwen-plus')
    const password = screen.getByLabelText('API Key')
    await userEvent.clear(password)
    await userEvent.type(password, 'bad-key')

    await userEvent.click(screen.getByRole('button', { name: '测试连通性' }))

    await waitFor(() => {
      expect(screen.getByText(/认证失败/)).toBeInTheDocument()
      expect(screen.getByText(/bad key/)).toBeInTheDocument()
    })
  })

  it('lets the user download and delete an existing backup', async () => {
    backupListMock.mockReturnValue({
      data: [{ name: '20260728T000000Z.zip', bytes: 1024, created_at: '2026-07-28T00:00:00Z' }],
    })
    const user = userEvent.setup()
    renderWithProviders(<ConfigPage />)

    await user.click(screen.getByRole('tab', { name: '运行默认' }))
    expect(await screen.findByText('20260728T000000Z.zip')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '下载该备份' }))
    expect(downloadBackupMock).toHaveBeenCalledWith('20260728T000000Z.zip')

    await user.click(screen.getByRole('button', { name: '删除该备份' }))
    const popup = (await screen.findByText('删除该备份', { selector: '.ant-popconfirm-title' }))
      .closest('.ant-popconfirm')! as HTMLElement
    await user.click(within(popup).getByRole('button', { name: /删\s?除/ }))
    await waitFor(() => {
      expect(deleteBackupMock).toHaveBeenCalledWith('20260728T000000Z.zip')
    })
  })

  it('filters the whitelist by profile and paginates long lists', async () => {
    const entries: WhitelistFixture[] = [
      ...Array.from({ length: 9 }, (_, i) => ({
        target_profile: 'profile-a',
        response: `a-response-${i}`,
        response_excerpt: `a-response-${i}`,
        added_at: '2026-07-28T00:00:00Z',
      })),
      {
        target_profile: 'profile-b',
        response: 'b-response',
        response_excerpt: 'b-response',
        added_at: '2026-07-28T00:00:00Z',
      },
    ]
    whitelistMock.mockReturnValue({ data: entries, refetch: vi.fn() })
    const user = userEvent.setup()
    renderWithProviders(<ConfigPage />)

    await user.click(screen.getByRole('tab', { name: '白名单' }))
    expect(await screen.findByText('a-response-0')).toBeInTheDocument()
    // 10 entries total, page size 8 → pagination shows and only page 1 renders.
    expect(screen.queryByText('a-response-8')).not.toBeInTheDocument()
    expect(screen.getByText('2', { selector: '.ant-pagination-item-2 a' })).toBeInTheDocument()

    // Filtering to profile-b narrows to its single entry.
    fireEvent.mouseDown(screen.getByRole('combobox'))
    await user.click((await screen.findAllByText('profile-b')).at(-1)!)
    expect(await screen.findByText('b-response')).toBeInTheDocument()
    expect(screen.queryByText('a-response-0')).not.toBeInTheDocument()
  })
})
