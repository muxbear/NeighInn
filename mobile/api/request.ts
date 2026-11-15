import { env } from '../config/env'
import { ERROR_MESSAGES } from '../config/constants'
import { ApiError } from './errors'
import { mockRequest } from './mock'
import { normalizePageResult } from './pagination'
import { createTraceId, logger } from '../utils/logger'
import { secureStorage } from '../utils/storage'
import { createIdempotencyKey } from '../utils/idempotency'

export type RequestMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface RequestOptions {
  url: string
  method?: RequestMethod
  data?: Record<string, any>
  headers?: Record<string, string>
  /** 是否携带登录态，默认 true */
  auth?: boolean
  /** 写操作默认自动生成幂等键 */
  idempotent?: boolean
  loading?: boolean
  timeout?: number
  /** GET 网络错误/5xx 自动重试一次 */
  retry?: boolean
}

export interface RequestMeta {
  traceId: string
  duration: number
  status: number
}

let loadingCount = 0

function showLoading(): void {
  loadingCount += 1
  if (loadingCount === 1 && typeof uni !== 'undefined') {
    uni.showLoading({ title: '加载中', mask: true })
  }
}

function hideLoading(): void {
  loadingCount = Math.max(0, loadingCount - 1)
  if (loadingCount === 0 && typeof uni !== 'undefined') {
    uni.hideLoading()
  }
}

function buildHeaders(options: RequestOptions): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers ?? {}),
  }
  if (options.auth !== false) {
    const token = secureStorage.getAccessToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  const method = options.method ?? 'GET'
  if (method !== 'GET' && options.idempotent !== false && !headers['X-Idempotency-Key']) {
    headers['X-Idempotency-Key'] = createIdempotencyKey('http')
  }
  headers['X-Trace-Id'] = createTraceId()
  return headers
}

function unwrap<T>(response: any, traceId: string): T {
  const status = response?.statusCode ?? 0
  if (status < 200 || status >= 300) {
    throw new ApiError(status === 0 ? 50000 : status, '网络请求失败', traceId, status)
  }
  const body = response?.data
  if (!body || typeof body !== 'object') {
    throw new ApiError(50000, ERROR_MESSAGES[50000], traceId, status)
  }
  if (body.code !== 0) {
    const message = body.message || ERROR_MESSAGES[body.code] || '请求失败'
    throw new ApiError(body.code, message, body.traceId || traceId, status)
  }
  return normalizePageResult<T>(body.data)
}

async function refreshToken(): Promise<boolean> {
  const refresh = secureStorage.getRefreshToken()
  if (!refresh) return false
  try {
    const data = await mockOrReal<{ accessToken: string; refreshToken: string }>(
      {
        url: '/auth/token/refresh',
        method: 'POST',
        data: { refreshToken: refresh },
        auth: false,
        idempotent: false,
      },
      true,
    )
    secureStorage.setTokens(data.accessToken, data.refreshToken)
    return true
  } catch (error) {
    logger.warn('Request', 'refresh token failed', error)
    return false
  }
}

export function redirectToLogin(): void {
  secureStorage.clear()
  if (typeof uni === 'undefined') return
  uni.reLaunch({ url: '/pages/auth/login' })
}

async function mockOrReal<T>(options: RequestOptions, skipRefresh = false): Promise<T> {
  const method = options.method ?? 'GET'
  const headers = buildHeaders(options)
  const traceId = headers['X-Trace-Id']
  const startedAt = Date.now()

  if (options.loading) showLoading()

  try {
    let result: T
    if (env.mock) {
      result = await mockRequest<T>({
        url: options.url,
        method,
        data: options.data,
        headers,
      })
    } else {
      result = await new Promise<T>((resolve, reject) => {
        uni.request({
          url: `${env.baseUrl}${options.url}`,
          method,
          data: options.data,
          header: headers,
          timeout: options.timeout ?? env.requestTimeout,
          success: (response: any) => {
            try {
              resolve(unwrap<T>(response, traceId))
            } catch (error) {
              reject(error)
            }
          },
          fail: (error: any) => {
            reject(new ApiError(50000, '网络连接失败，请检查网络', traceId, 0))
            logger.warn('Request', 'network fail', { url: options.url, error: error?.errMsg })
          },
        })
      })
    }

    logger.debug('Request', `${method} ${options.url}`, {
      status: 200,
      duration: Date.now() - startedAt,
      traceId,
    })
    return result
  } catch (error) {
    const apiError = error instanceof ApiError ? error : new ApiError(50000, '请求失败', traceId)

    if (apiError.code === 40101 && !skipRefresh && options.auth !== false) {
      const refreshed = await refreshToken()
      if (refreshed) {
        return mockOrReal<T>(options, true)
      }
      redirectToLogin()
      throw new ApiError(40101, ERROR_MESSAGES[40101], traceId, apiError.httpStatus)
    }

    if (apiError.code === 40101 && skipRefresh) {
      redirectToLogin()
    }

    const canRetry =
      method === 'GET' &&
      options.retry !== false &&
      (apiError.code >= 500 || apiError.code === 50000)
    if (canRetry && !skipRefresh) {
      logger.warn('Request', `retry GET ${options.url}`, { traceId })
      return mockOrReal<T>(options, true)
    }

    logger.warn('Request', `${method} ${options.url} failed`, {
      code: apiError.code,
      duration: Date.now() - startedAt,
      traceId: apiError.traceId,
    })
    throw apiError
  } finally {
    if (options.loading) hideLoading()
  }
}

export function request<T>(options: RequestOptions): Promise<T> {
  return mockOrReal<T>(options)
}

export function get<T>(url: string, data?: Record<string, any>, options: Partial<RequestOptions> = {}): Promise<T> {
  return request<T>({ url, method: 'GET', data, ...options })
}

export function post<T>(url: string, data?: Record<string, any>, options: Partial<RequestOptions> = {}): Promise<T> {
  return request<T>({ url, method: 'POST', data, ...options })
}

export function put<T>(url: string, data?: Record<string, any>, options: Partial<RequestOptions> = {}): Promise<T> {
  return request<T>({ url, method: 'PUT', data, ...options })
}

export function del<T>(url: string, data?: Record<string, any>, options: Partial<RequestOptions> = {}): Promise<T> {
  return request<T>({ url, method: 'DELETE', data, ...options })
}
