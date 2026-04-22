import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearToken, client } from '../api/client'
import { renderWithProviders } from '../test/test-utils'
import { Login } from './Login'

describe('Login', () => {
  beforeEach(() => {
    clearToken()
  })

  afterEach(() => {
    vi.restoreAllMocks()
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
})
