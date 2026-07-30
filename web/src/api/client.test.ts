import { AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearToken, client, getToken, setToken } from './client'

describe('api client', () => {
  beforeEach(() => {
    clearToken()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    clearToken()
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
})
