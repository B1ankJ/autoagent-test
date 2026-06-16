import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { client } from '../../api/client'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import { TestsQuick } from './Quick'

vi.mock('../../api/profiles', () => ({
  useProfiles: () => ({
    data: [
      { name: 'fake_api', platform: 'api' },
      { name: 'fake_web', platform: 'web' },
      { name: 'fake_android', platform: 'android' },
    ],
  }),
}))

vi.mock('../../api/tests', () => ({
  useRunAsync: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAsyncResult: () => ({ data: undefined }),
}))

vi.mock('../../api/client', () => ({
  client: {
    post: vi.fn(),
  },
}))

describe('TestsQuick', () => {
  function getSelectCombobox(index: number) {
    return screen.getAllByRole('combobox')[index] as HTMLElement
  }

  it('shows Android mode and filters profiles to android', async () => {
    renderWithProviders(<TestsQuick />, { initialPath: '/tests/quick' })

    fireEvent.mouseDown(getSelectCombobox(0))
    expect(await screen.findByText('Android (GUI)')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Android (GUI)'))

    fireEvent.mouseDown(getSelectCombobox(1))
    await waitFor(() => {
      const labels = screen.getAllByRole('option').map((node) => node.textContent)
      expect(labels).toContain('fake_android')
      expect(labels).not.toContain('fake_web')
      expect(labels).not.toContain('fake_api')
    })
  })

  it('renders rule and llm extraction panels for sync results', async () => {
    vi.mocked(client.post).mockResolvedValue({
      data: {
        id: 'quick-1',
        status: 'done',
        responses: ['rule result'],
        llm_responses: ['llm result'],
        llm_errors: [null],
        duration_ms: 1234,
      },
    })

    renderWithProviders(<TestsQuick />, { initialPath: '/tests/quick' })

    fireEvent.mouseDown(getSelectCombobox(0))
    await userEvent.click(await screen.findByText('Android (GUI)'))

    await waitFor(() => {
      expect(screen.getAllByRole('combobox')).toHaveLength(2)
    })
    fireEvent.mouseDown(getSelectCombobox(1))
    await userEvent.click((await screen.findAllByText('fake_android')).at(-1)!)
    await userEvent.type(screen.getByRole('textbox', { name: /Prompts/i }), '你好')
    await userEvent.click(screen.getByRole('button', { name: /运\s*行/ }))

    expect(await screen.findByText(/结果 · done/)).toBeInTheDocument()
    expect(await screen.findByText(/主响应/)).toBeInTheDocument()
    expect(screen.getByText(/LLM 复核/)).toBeInTheDocument()
    expect(screen.getByText('rule result')).toBeInTheDocument()
    expect(screen.getByText('llm result')).toBeInTheDocument()
  })

  it('shows an explicit notice when llm extraction is not enabled', async () => {
    vi.mocked(client.post).mockResolvedValue({
      data: {
        id: 'quick-2',
        status: 'done',
        responses: ['rule only'],
        duration_ms: 567,
      },
    })

    renderWithProviders(<TestsQuick />, { initialPath: '/tests/quick' })

    fireEvent.mouseDown(getSelectCombobox(1))
    await userEvent.click((await screen.findAllByText('fake_api')).at(-1)!)
    await userEvent.type(screen.getByRole('textbox', { name: /Prompts/i }), 'hello')
    await userEvent.click(screen.getByRole('button', { name: /运\s*行/ }))

    expect(await screen.findByText(/结果 · done/)).toBeInTheDocument()
    expect(await screen.findByText('未启用 LLM 提取')).toBeInTheDocument()
  })
})
