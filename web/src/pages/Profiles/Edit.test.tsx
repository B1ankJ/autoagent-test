import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { client } from '../../api/client'
import { renderWithProviders } from '../../test/test-utils'
import { ProfileEdit } from './Edit'

vi.mock('../../components/YamlEditor', () => ({
  YamlEditor: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <textarea data-testid="yaml" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}))

describe('ProfileEdit', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('validates YAML via API when clicking 校验', async () => {
    const spy = vi.spyOn(client, 'post').mockResolvedValueOnce({ data: { ok: true } } as never)

    renderWithProviders(<ProfileEdit />, { initialPath: '/profiles/new' })

    await userEvent.type(screen.getByTestId('yaml'), 'platform: api\nname: x\n')
    await userEvent.click(screen.getByRole('button', { name: /校\s*验/ }))

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith('/profiles/validate', expect.any(Object))
    })
  })
})
