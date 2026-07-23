import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import { ConfigPage } from './Config'

const { testLlmMock } = vi.hoisted(() => ({
  testLlmMock: vi.fn(),
}))

vi.mock('../api/config', () => ({
  useVLM: () => ({ data: { base_url: 'https://old', model: 'old-model', api_key: 'old-key' } }),
  useSaveVLM: () => ({ isPending: false, mutateAsync: vi.fn(async (body) => body) }),
  useTestLLM: () => ({ isPending: false, mutateAsync: testLlmMock }),
  useDefaults: () => ({ data: { api_timeout_sec: 60, gui_timeout_sec: 180, retry: 2, concurrency: 1, verbose_logs: true } }),
  useSaveDefaults: () => ({ isPending: false, mutateAsync: vi.fn(async (body) => body) }),
  useNotifications: () => ({ data: { enabled: false, webhook_url: '', secret: '', empty_response_threshold: 3, same_response_enabled: false, same_response_threshold: 3, same_response_auto_reinit: false, at_mobiles: [], at_all: false, app_base_url: '' } }),
  useSaveNotifications: () => ({ isPending: false, mutateAsync: vi.fn(async (body) => body) }),
  useTestNotifications: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useWhitelist: () => ({ data: [], refetch: vi.fn() }),
  useRemoveWhitelist: () => ({ isPending: false, mutateAsync: vi.fn() }),
  usePreviewLogsCleanup: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useRunLogsCleanup: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useBackupList: () => ({ data: [] }),
  useRunBackup: () => ({ isPending: false, mutateAsync: vi.fn() }),
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
})
