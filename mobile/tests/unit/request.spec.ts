import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { request } from '../../api/request'
import { env } from '../../config/env'

function stubUniResponse(statusCode: number, data: unknown): void {
  vi.stubGlobal('uni', {
    getStorageSync: () => '',
    setStorageSync: () => undefined,
    removeStorageSync: () => undefined,
    request: (options: any) => options.success({ statusCode, data }),
  })
}

beforeAll(() => {
  env.mock = false
  env.baseUrl = 'http://127.0.0.1:5193/api/v1'
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request query params', () => {
  it('drops undefined and null GET params before calling uni.request', async () => {
    let captured: any = null
    vi.stubGlobal('uni', {
      getStorageSync: () => '',
      setStorageSync: () => undefined,
      removeStorageSync: () => undefined,
      request: (options: any) => {
        captured = options
        options.success({ statusCode: 200, data: { code: 0, message: 'ok', data: { items: [] } } })
      },
    })

    await request({
      url: '/conversations/1/messages',
      method: 'GET',
      // H5 会把 undefined/null 序列化成空字符串，后端 int 参数会因此 422
      data: { beforeSeq: undefined, afterSeq: null, limit: 30 },
    })

    expect(captured.data).toEqual({ limit: 30 })
  })
})

describe('request error handling', () => {
  it('surfaces the service message for non-2xx responses', async () => {
    stubUniResponse(400, {
      code: 40001,
      message: '请选择完整的成色档位（五档）',
      data: null,
      traceId: 'trace-400',
    })

    await expect(request({ url: '/items', method: 'POST', data: {} })).rejects.toMatchObject({
      code: 40001,
      message: '请选择完整的成色档位（五档）',
      httpStatus: 400,
      traceId: 'trace-400',
    })
  })

  it('parses JSON string bodies from non-2xx responses', async () => {
    stubUniResponse(403, JSON.stringify({
      code: 40304,
      message: '请先完成实名与业主认证后再发布物品',
      data: null,
      traceId: 'trace-403',
    }))

    await expect(request({ url: '/items', method: 'POST', data: {} })).rejects.toMatchObject({
      code: 40304,
      message: '请先完成实名与业主认证后再发布物品',
      httpStatus: 403,
    })
  })

  it('falls back to a network message when the error body is not JSON', async () => {
    stubUniResponse(502, '<html>Bad Gateway</html>')

    await expect(request({ url: '/items', method: 'POST', data: {} })).rejects.toMatchObject({
      code: 502,
      message: '网络请求失败',
      httpStatus: 502,
    })
  })
})
