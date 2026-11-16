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
