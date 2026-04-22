import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { clearToken, setToken } from '../api/client'
import { renderWithProviders } from '../test/test-utils'
import { RequireAuth } from './RequireAuth'

describe('RequireAuth', () => {
  afterEach(() => {
    clearToken()
  })

  it('redirects unauthenticated users to /login', () => {
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<div>login-page</div>} />
        <Route
          path="/protected"
          element={
            <RequireAuth>
              <div>secret</div>
            </RequireAuth>
          }
        />
      </Routes>,
      { initialPath: '/protected' },
    )

    expect(screen.getByText('login-page')).toBeInTheDocument()
  })

  it('renders children when authenticated', () => {
    setToken('t')

    renderWithProviders(
      <Routes>
        <Route
          path="/protected"
          element={
            <RequireAuth>
              <div>secret</div>
            </RequireAuth>
          }
        />
      </Routes>,
      { initialPath: '/protected' },
    )

    expect(screen.getByText('secret')).toBeInTheDocument()
  })
})
