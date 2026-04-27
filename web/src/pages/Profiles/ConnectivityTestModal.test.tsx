import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../../test/test-utils'
import { ConnectivityTestModal } from './ConnectivityTestModal'

const { mutateAsyncMock, runSyncState } = vi.hoisted(() => ({
  mutateAsyncMock: vi.fn(),
  runSyncState: {
    data: undefined as
      | {
          id: string
          status: 'done' | 'failed'
          responses: string[]
          llm_responses?: string[]
          llm_errors?: Array<string | null>
          duration_ms?: number
          error?: string
        }
      | undefined,
    error: null as Error | null,
  },
}))

vi.mock('../../api/tests', () => ({
  useRunSync: () => ({
    mutateAsync: mutateAsyncMock,
    isPending: false,
    data: runSyncState.data,
    error: runSyncState.error,
  }),
}))

describe('ConnectivityTestModal', () => {
  afterEach(() => {
    vi.clearAllMocks()
    runSyncState.data = undefined
    runSyncState.error = null
  })

  it('shows rule and llm responses separately after a successful run', async () => {
    runSyncState.data = {
      id: 'conn-1',
      status: 'done',
      responses: ['规则结果'],
      llm_responses: ['LLM 结果'],
      llm_errors: [null],
      duration_ms: 1234,
    }

    renderWithProviders(
      <ConnectivityTestModal open profileName="qwen_llm" mode="gui_android" onClose={() => {}} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /发\s*送/ }))

    await waitFor(() => {
      expect(mutateAsyncMock).toHaveBeenCalled()
      expect(screen.getByText('规则提取')).toBeInTheDocument()
      expect(screen.getByText('LLM 提取')).toBeInTheDocument()
      expect(screen.getByText('规则结果')).toBeInTheDocument()
      expect(screen.getByText('LLM 结果')).toBeInTheDocument()
    })
  })

  it('shows llm disabled hint when sync result has no llm extraction arrays', async () => {
    runSyncState.data = {
      id: 'conn-2',
      status: 'done',
      responses: ['规则结果'],
      duration_ms: 2345,
    }

    renderWithProviders(
      <ConnectivityTestModal open profileName="plain_profile" mode="gui_android" onClose={() => {}} />,
    )

    await userEvent.click(screen.getByRole('button', { name: /发\s*送/ }))

    await waitFor(() => {
      expect(screen.getByText('未启用 LLM 提取')).toBeInTheDocument()
    })
  })
})
