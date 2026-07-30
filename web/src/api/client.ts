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

// Requests made with `responseType: 'blob'` (file downloads) still get their
// error body delivered as a Blob, even though the server sent JSON — axios
// respects the requested responseType regardless of status code.
// normalizeError can't read `.detail` off a Blob, so it silently fell back
// to a generic "未知错误" for every failed download, hiding the real reason
// (e.g. "results already archived"). Read it back out to plain JSON first.
function readBlobAsText(blob: Blob): Promise<string> {
  // Blob.prototype.text() isn't implemented everywhere in the test
  // environment (jsdom) this ships with — FileReader is the same read,
  // more broadly supported, and works fine in real browsers too.
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

async function unwrapBlobErrorBody(error: AxiosError): Promise<void> {
  const data = error.response?.data
  if (!(data instanceof Blob) || !data.type.includes('json')) return
  try {
    error.response!.data = JSON.parse(await readBlobAsText(data))
  } catch {
    // Not actually JSON despite the content-type — leave as-is and let
    // normalizeError's existing fallback handle it.
  }
}

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    await unwrapBlobErrorBody(error)
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
