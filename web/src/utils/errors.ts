export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
    this.name = 'ApiError'
  }
}

export function normalizeError(err: unknown): ApiError {
  if (err instanceof ApiError) {
    return err
  }

  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { status: number; data?: unknown } }).response
    if (response) {
      const data = response.data
      let detail = '未知错误'
      if (typeof data === 'object' && data !== null && 'detail' in data) {
        const value = (data as { detail: unknown }).detail
        if (typeof value === 'string') {
          detail = value
        } else if (Array.isArray(value)) {
          detail = value.map((item) => JSON.stringify(item)).join('\n')
        } else {
          detail = JSON.stringify(value)
        }
      }
      return new ApiError(response.status, detail)
    }
  }

  if (err instanceof Error) {
    return new ApiError(0, err.message)
  }

  return new ApiError(0, '服务不可达，请检查后端')
}
