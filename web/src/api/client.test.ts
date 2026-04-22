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
})
