import { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    // Serialize the full target (path + query + hash) so query-bearing pages
    // like /batches?q=foo&page=2 survive the round trip through /login.
    const from = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" state={{ from }} replace />
  }

  return <>{children}</>
}
