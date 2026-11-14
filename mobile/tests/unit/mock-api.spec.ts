import { beforeAll, describe, expect, it } from 'vitest'
import { mockRequest } from '../../api/mock'
import { env } from '../../config/env'
import type { HomeBundle, PageResult } from '../../models'
import type { Item, Order } from '../../models'

beforeAll(() => {
  env.mockLatency = 0
})

describe('mock api', () => {
  it('returns a complete home bundle', async () => {
    const home = await mockRequest<HomeBundle>({ url: '/home', method: 'GET' })
    expect(home.community.name).toBe('阳光花园小区')
    expect(home.zones).toHaveLength(4)
    expect(home.broadcasts).toHaveLength(4)
    expect(home.hotItems.length).toBeGreaterThan(0)
    expect(home.lifePosts.length).toBeGreaterThan(0)
  })

  it('filters items by zone and keyword', async () => {
    const gifts = await mockRequest<PageResult<Item>>({ url: '/items?zone=gift&page=1&pageSize=20', method: 'GET' })
    expect(gifts.list.length).toBeGreaterThan(0)
    expect(gifts.list.every((item) => item.type === '免费')).toBe(true)

    const giftsAllCategories = await mockRequest<PageResult<Item>>({
      url: '/items?zone=gift&category=%E5%85%A8%E9%83%A8&page=1&pageSize=4',
      method: 'GET',
    })
    expect(giftsAllCategories.list).toHaveLength(4)
    expect(giftsAllCategories.hasMore).toBe(true)

    const search = await mockRequest<PageResult<Item>>({ url: '/items?keyword=儿童椅', method: 'GET' })
    expect(search.list.some((item) => item.title.indexOf('儿童') >= 0)).toBe(true)
  })

  it('logs in with a mock sms code', async () => {
    const result = await mockRequest<{ accessToken: string; profile: { nickname: string } }>({
      url: '/auth/login/sms',
      method: 'POST',
      data: { phone: '13800005628', code: '123456' },
    })
    expect(result.accessToken).toContain('mock-access')
    expect(result.profile.nickname).toBeTruthy()
  })

  it('creates and pays a monetary order', async () => {
    const created = await mockRequest<{ orderId: string; orderNo: string; amount: number }>({
      url: '/orders',
      method: 'POST',
      data: { itemId: 'i1', tradeType: '出售' },
    })
    expect(created.orderId).toBeTruthy()

    const prepay = await mockRequest<{ orderNo: string }>({
      url: '/payments/prepay',
      method: 'POST',
      data: { orderId: created.orderId, method: 'wechat' },
    })
    expect(prepay.orderNo).toBe(created.orderNo)

    const order = await mockRequest<Order>({ url: `/orders/${created.orderId}`, method: 'GET' })
    expect(order.status).toBe('ESCROWED')
    expect(order.canInspect).toBe(true)
  })

  it('advances AI audit progress', async () => {
    let last = null as any
    for (let i = 0; i < 6; i += 1) {
      last = await mockRequest<{ status: string; progress: number }>({
        url: '/items/mi2/audit-progress',
        method: 'GET',
      })
    }
    expect(last.status).toBe('PASSED')
    expect(last.progress).toBe(100)
  })
})
