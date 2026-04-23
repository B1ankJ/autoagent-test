import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import { BatchNew } from './New'

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
  useCreateBatchJson: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUploadBatch: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

describe('BatchNew', () => {
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
