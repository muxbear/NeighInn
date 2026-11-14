export class ApiError extends Error {
  code: number
  traceId: string
  httpStatus?: number

  constructor(code: number, message: string, traceId = '', httpStatus?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.traceId = traceId
    this.httpStatus = httpStatus
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.message
  if (error instanceof Error) return error.message
  return '网络开小差了，请稍后重试'
}
