import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SESSION_EXPIRED_KEY, clearToken, client } from '../api/client'
import { renderWithProviders } from '../test/test-utils'
import { Login } from './Login'

describe('Login', () => {
  beforeEach(() => {
    clearToken()
    sessionStorage.removeItem(SESSION_EXPIRED_KEY)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    sessionStorage.removeItem(SESSION_EXPIRED_KEY)
  })

  it('submits credentials and stores token', async () => {
    vi.spyOn(client, 'post').mockResolvedValueOnce({
      data: { token: 'tok', expires_at: '2099-01-01' },
    } as never)

    renderWithProviders(<Login />, { initialPath: '/login' })

    await userEvent.type(screen.getByLabelText('用户名'), 'admin')
    await userEvent.type(screen.getByLabelText('密码'), 'pw')
    await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }))

    await waitFor(() => {
      expect(localStorage.getItem('autoagent_token')).toBe('tok')
    })
  })

  it('shows a session-expired message when the client interceptor set the flag before redirecting', async () => {
    // Regression: a 401 mid-session hard-redirected to /login with zero
    // explanation — the flag is client.ts's only way to carry that context
    // across a redirect that destroys the whole React tree.
    sessionStorage.setItem(SESSION_EXPIRED_KEY, '1')

    renderWithProviders(<Login />, { initialPath: '/login' })

    expect(await screen.findByText('登录已过期,请重新登录')).toBeInTheDocument()
    // Consumed once — a plain page refresh afterward shouldn't re-show it.
    expect(sessionStorage.getItem(SESSION_EXPIRED_KEY)).toBeNull()
  })
})
