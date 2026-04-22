import axios, { AxiosError, AxiosHeaders } from 'axios'
import { ApiError, normalizeError } from '../utils/errors'

const TOKEN_KEY = 'autoagent_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
})

client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    const headers = AxiosHeaders.from(config.headers)
    headers.set('Authorization', `Bearer ${token}`)
    config.headers = headers
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const apiError: ApiError = normalizeError(error)
    if (apiError.status === 401) {
      clearToken()
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(apiError)
  },
)
