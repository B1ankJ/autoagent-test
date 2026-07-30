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

    // YamlEditor is lazy-loaded; wait for the Suspense boundary to resolve.
    await userEvent.type(await screen.findByTestId('yaml'), 'platform: api\nname: x\n')
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

  it('warns before leaving a dirty new-profile draft via the 配置档 breadcrumb', async () => {
    renderWithProviders(<ProfileEdit />, { initialPath: '/profiles/new' })

    await userEvent.type(await screen.findByTestId('yaml'), 'platform: api\n')
    await userEvent.click(screen.getByText('配置档'))

    const discardButton = await screen.findByRole('button', { name: /放弃并离开/ })

    // Cancelling stays put — the editor (and its typed content) is still there.
    await userEvent.click(screen.getByRole('button', { name: /取\s?消/ }))
    await waitFor(() => expect(discardButton).not.toBeInTheDocument())
    expect(screen.getByTestId('yaml')).toHaveValue('platform: api\n')
  })

  it('navigates straight to 配置档 with no warning when nothing has been typed', async () => {
    renderWithProviders(<ProfileEdit />, { initialPath: '/profiles/new' })

    await screen.findByTestId('yaml')
    await userEvent.click(screen.getByText('配置档'))

    expect(screen.queryByRole('button', { name: /放弃并离开/ })).not.toBeInTheDocument()
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
