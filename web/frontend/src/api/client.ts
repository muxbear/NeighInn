import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'

export class ApiError extends Error {
  code: number
  traceId?: string
  constructor(code: number, message: string, traceId?: string) {
    super(message)
    this.code = code
    this.traceId = traceId
  }
}

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1')}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

export const http = axios.create({
  baseURL: '/api/v1/admin',
  timeout: 15000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  const csrf = getCookie('ni_csrf')
  if (csrf && config.method && !['get', 'head', 'options'].includes(config.method.toLowerCase())) {
    config.headers['X-CSRF-Token'] = csrf
  }
  // crypto.randomUUID 仅在安全上下文（HTTPS / localhost）可用；
  // HTTP 联调时退化为随机十六进制串，避免请求拦截器直接抛错。
  const traceSource =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().replace(/-/g, '')
      : Math.random().toString(16).slice(2) + Date.now().toString(16)
  config.headers['X-Trace-Id'] = traceSource.slice(0, 16)
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body.code === 'number' && body.code !== 0) {
      return Promise.reject(new ApiError(body.code, body.message || '请求失败', body.traceId))
    }
    return body?.data
  },
  (error: AxiosError<any>) => {
    const body = error.response?.data
    const message = body?.message || error.message || '网络异常'
    if (error.response?.status === 401 && !window.location.pathname.startsWith('/login')) {
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
    }
    return Promise.reject(new ApiError(body?.code ?? 50000, message, body?.traceId))
  },
)

export function request<T = any>(config: AxiosRequestConfig): Promise<T> {
  return http.request(config) as unknown as Promise<T>
}
