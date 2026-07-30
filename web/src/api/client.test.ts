import { AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SESSION_EXPIRED_KEY, clearToken, client, getToken, setToken } from './client'

describe('api client', () => {
  beforeEach(() => {
    clearToken()
    sessionStorage.removeItem(SESSION_EXPIRED_KEY)
    vi.restoreAllMocks()
  })

  afterEach(() => {
    clearToken()
    sessionStorage.removeItem(SESSION_EXPIRED_KEY)
    vi.restoreAllMocks()
  })

  it('stores and reads token in localStorage', () => {
    setToken('abc')
    expect(getToken()).toBe('abc')

    clearToken()
    expect(getToken()).toBeNull()
  })

  it('injects Authorization header when token present', async () => {
    setToken('xyz')

    const handler = client.interceptors.request.handlers?.[0]
    if (!handler?.fulfilled) {
      throw new Error('request interceptor is not registered')
    }
    const config = await handler.fulfilled?.({
      headers: AxiosHeaders.from({}),
    } as never)

    expect(AxiosHeaders.from(config?.headers).get('Authorization')).toBe('Bearer xyz')
  })

  it('unwraps a JSON error body delivered as a Blob (responseType: blob downloads)', async () => {
    // axios respects the requested responseType regardless of status code,
    // so a failed download's error body arrives as a Blob even though the
    // server sent a normal JSON { detail } error — without unwrapping it,
    // normalizeError can't read `.detail` off a Blob and falls back to a
    // generic "未知错误", hiding the real backend reason.
    const handler = client.interceptors.response.handlers?.[0]
    if (!handler?.rejected) {
      throw new Error('response interceptor is not registered')
    }

    const blob = new Blob([JSON.stringify({ detail: '结果已归档,无法下载' })], {
      type: 'application/json',
    })
    const error = {
      response: { status: 409, data: blob },
      isAxiosError: true,
    } as never

    await expect(handler.rejected(error)).rejects.toMatchObject({
      status: 409,
      message: '结果已归档,无法下载',
    })
  })

  it('sets a session-expired flag and clears the token before redirecting on a mid-session 401', async () => {
    // Regression: a token expiring while the user is actively using the
    // app hard-redirected straight to /login with zero explanation — this
    // flag is the only way to carry that context across a redirect that
    // destroys the whole React tree (Login reads it and shows a message).
    // jsdom's window.location.assign isn't configurable enough for
    // vi.spyOn — replace the whole location object for this test instead.
    const originalLocation = window.location
    const assignSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    })
    setToken('xyz')

    const handler = client.interceptors.response.handlers?.[0]
    if (!handler?.rejected) {
      throw new Error('response interceptor is not registered')
    }

    const error = {
      response: { status: 401, data: { detail: 'invalid token' } },
      isAxiosError: true,
    } as never

    await expect(handler.rejected(error)).rejects.toMatchObject({ status: 401 })

    expect(getToken()).toBeNull()
    expect(sessionStorage.getItem(SESSION_EXPIRED_KEY)).toBe('1')
    expect(assignSpy).toHaveBeenCalledWith('/login')

    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
  })
})
