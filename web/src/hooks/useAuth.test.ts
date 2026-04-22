import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useAuth } from './useAuth'

describe('useAuth', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('reflects token changes across instances', () => {
    const first = renderHook(() => useAuth())
    const second = renderHook(() => useAuth())

    expect(first.result.current.isAuthenticated).toBe(false)

    act(() => first.result.current.login('t1'))

    expect(first.result.current.token).toBe('t1')
    expect(second.result.current.token).toBe('t1')

    act(() => second.result.current.logout())

    expect(first.result.current.isAuthenticated).toBe(false)
  })
})
