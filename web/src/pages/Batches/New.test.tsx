import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import { BatchNew } from './New'

const { createJsonMock } = vi.hoisted(() => ({ createJsonMock: vi.fn() }))

vi.mock('../../api/profiles', () => ({
  useProfiles: () => ({
    data: [
      { name: 'fake_api', platform: 'api' },
      { name: 'fake_web', platform: 'web' },
      { name: 'fake_android', platform: 'android' },
    ],
  }),
}))

vi.mock('../../api/batches', () => ({
  useCreateBatchJson: () => ({ mutateAsync: createJsonMock, isPending: false }),
  useUploadBatch: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

describe('BatchNew', () => {
  afterEach(() => {
    createJsonMock.mockReset()
    localStorage.clear()
  })

  it('shows a persistent error alert (not just a transient toast) when creating a batch fails', async () => {
    // Regression: a failed submit only showed a message.error toast, which
    // disappears in a few seconds — long enough to miss a detail like
    // "sample s2 mode=api != batch mode=gui_android" naming which row is
    // wrong. The backend returns a plain string (no per-field structure),
    // so this can't drive Form.Item-level errors, but it can at least stay
    // on screen instead of vanishing.
    createJsonMock.mockRejectedValueOnce(
      new Error('sample s1 mode=api != batch mode=gui_android'),
    )
    renderWithProviders(<BatchNew />, { initialPath: '/batches/new' })

    await userEvent.type(screen.getByLabelText('名称'), 'nightly')
    fireEvent.mouseDown(screen.getAllByRole('combobox')[1]!) // 默认 Profile
    await userEvent.click((await screen.findAllByText('fake_api')).at(-1)!)
    await userEvent.type(screen.getByPlaceholderText('id'), 's1')
    await userEvent.type(
      screen.getByPlaceholderText('prompts（空行分隔多条，单条内可换行）'),
      'hi',
    )
    await userEvent.click(screen.getAllByRole('button', { name: /创\s?建/ })[0]!)

    expect(
      await screen.findByText('sample s1 mode=api != batch mode=gui_android'),
    ).toBeInTheDocument()
    // Still there after a beat — nothing auto-dismisses it like a toast would.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(
      screen.getByText('sample s1 mode=api != batch mode=gui_android'),
    ).toBeInTheDocument()
  })

  it('shows Android mode and filters profiles to android', async () => {
    renderWithProviders(<BatchNew />, { initialPath: '/batches/new' })

    fireEvent.mouseDown(screen.getAllByRole('combobox')[0]!)
    expect(await screen.findByText('Android (GUI)')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Android (GUI)'))

    fireEvent.mouseDown(screen.getAllByRole('combobox')[1]!)
    await waitFor(() => {
      const labels = screen.getAllByRole('option').map((node) => node.textContent)
      expect(labels).toContain('fake_android')
      expect(labels).not.toContain('fake_web')
      expect(labels).not.toContain('fake_api')
    })
  })
})
