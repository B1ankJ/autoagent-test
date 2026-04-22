import { useCallback, useSyncExternalStore } from 'react'
import { clearToken, getToken, setToken } from '../api/client'

const listeners = new Set<() => void>()

function notify() {
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useAuth() {
  const token = useSyncExternalStore(subscribe, getToken, () => null)
  const login = useCallback((nextToken: string) => {
    setToken(nextToken)
    notify()
  }, [])
  const logout = useCallback(() => {
    clearToken()
    notify()
  }, [])

  return { token, isAuthenticated: !!token, login, logout }
}
