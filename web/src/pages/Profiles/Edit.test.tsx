import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { client } from '../../api/client'
import { renderWithProviders } from '../../test/test-utils'
import { ProfileEdit } from './Edit'

vi.mock('./ConnectivityTestModal', () => ({
  ConnectivityTestModal: ({ open, profileName }: { open: boolean; profileName: string }) =>
    open ? <div>modal:{profileName}</div> : null,
}))

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

  it('enables connectivity test for web profiles', async () => {
    vi.spyOn(client, 'get').mockResolvedValueOnce({
      data: { yaml: 'platform: web\nname: web_demo\n' },
    } as never)

    renderWithProviders(
      <Routes>
        <Route path="/profiles/:name" element={<ProfileEdit />} />
      </Routes>,
      { initialPath: '/profiles/web_demo' },
    )

    const button = screen.getByRole('button', { name: '连通性测试' })
    await waitFor(() => {
      expect(button).toBeEnabled()
    })

    await userEvent.click(button)
    expect(screen.getByText('modal:web_demo')).toBeInTheDocument()
  })

  it('enables connectivity test for android profiles', async () => {
    vi.spyOn(client, 'get').mockResolvedValueOnce({
      data: { yaml: 'platform: android\nname: fake_android\npackage: demo\n' },
    } as never)

    renderWithProviders(
      <Routes>
        <Route path="/profiles/:name" element={<ProfileEdit />} />
      </Routes>,
      { initialPath: '/profiles/fake_android' },
    )

    const button = screen.getByRole('button', { name: '连通性测试' })
    await waitFor(() => {
      expect(button).toBeEnabled()
    })
  })
})
