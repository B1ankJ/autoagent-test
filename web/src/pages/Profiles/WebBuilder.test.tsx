import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import WebBuilder from './WebBuilder'

const { createSessionMock, closeSessionMock } = vi.hoisted(() => ({
  createSessionMock: vi.fn(),
  closeSessionMock: vi.fn(),
}))

vi.mock('../../api/webProfileBuilder', () => ({
  useCreateWebBuilderSession: () => ({ mutateAsync: createSessionMock, isPending: false }),
  useCloseWebBuilderSession: () => ({ mutateAsync: closeSessionMock, isPending: false }),
  useWebBuilderSession: () => ({ data: { id: 'sess-1', url: 'https://x', selections: {} } }),
  useWebBuilderScreenshot: () => ({ data: undefined, isFetching: false, refetch: vi.fn() }),
  usePickElement: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useClearSelection: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useGenerateWebProfile: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('../../api/config', () => ({
  useVLM: () => ({ data: null }),
}))

beforeEach(() => {
  createSessionMock.mockReset()
  closeSessionMock.mockReset()
  closeSessionMock.mockResolvedValue({ status: 'closed' })
})

it('closes the builder session on unmount, so abandoning the page (nav away, back button) does not leak the browser process', async () => {
  // Regression: the backend's in-memory session dict has no TTL/idle
  // reaper — closeSession was only ever called from handleSave/handleClose,
  // so any other way of leaving the page (sidebar nav, back button, tab
  // close) left a live Playwright browser process running forever.
  createSessionMock.mockResolvedValue({ id: 'sess-1' })
  const user = userEvent.setup()
  const { unmount } = renderWithProviders(<WebBuilder />)

  await user.type(screen.getByLabelText(/网址|URL/i) ?? screen.getByRole('textbox'), 'https://x')
  await user.click(screen.getByRole('button', { name: /启动|开始/ }))

  await waitFor(() => expect(createSessionMock).toHaveBeenCalled())
  expect(closeSessionMock).not.toHaveBeenCalled()

  unmount()

  expect(closeSessionMock).toHaveBeenCalledWith('sess-1')
})
