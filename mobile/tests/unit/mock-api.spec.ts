import { beforeAll, describe, expect, it } from 'vitest'
import { mockRequest } from '../../api/mock'
import { env } from '../../config/env'
import type {
  ChatMessage,
  CommunityBinding,
  Conversation,
  HomeBundle,
  PageResult,
  RegionNode,
  ServicePost,
} from '../../models'
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

  it('cascades regions and filters communities by street', async () => {
    const provinces = await mockRequest<RegionNode[]>({ url: '/regions/children', method: 'GET' })
    expect(provinces[0].name).toBe('浙江省')

    const cities = await mockRequest<RegionNode[]>({
      url: `/regions/children?parentId=${provinces[0].id}`,
      method: 'GET',
    })
    const districts = await mockRequest<RegionNode[]>({
      url: `/regions/children?parentId=${cities[0].id}`,
      method: 'GET',
    })
    const streets = await mockRequest<RegionNode[]>({
      url: `/regions/children?parentId=${districts[0].id}`,
      method: 'GET',
    })
    const communities = await mockRequest<CommunityBinding[]>({
      url: `/communities/search?streetId=${streets[0].id}`,
      method: 'GET',
    })
    expect(communities.length).toBeGreaterThan(0)
    expect(communities[0].street).toBe('文新街道')
    expect(communities[0].regionPath).toBe('浙江省 杭州市 西湖区 文新街道')

    // 不强制选择街道：区县/地市范围 + 关键词搜索
    const byRegion = await mockRequest<CommunityBinding[]>({
      url: `/communities/search?regionId=${districts[0].id}`,
      method: 'GET',
    })
    expect(byRegion.length).toBeGreaterThan(0)
    expect(byRegion.every((item) => item.regionId === districts[0].id)).toBe(true)

    const byCity = await mockRequest<CommunityBinding[]>({
      url: `/communities/search?cityId=${cities[0].id}`,
      method: 'GET',
    })
    expect(byCity.length).toBeGreaterThanOrEqual(byRegion.length)

    const byKeyword = await mockRequest<CommunityBinding[]>({
      url: `/communities/search?keyword=${encodeURIComponent('阳光')}`,
      method: 'GET',
    })
    expect(byKeyword.some((item) => item.name.includes('阳光'))).toBe(true)
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

  it('publishes a mutual aid offer and lists it back', async () => {
    const created = await mockRequest<ServicePost>({
      url: '/services',
      method: 'POST',
      data: {
        kind: 'OFFER',
        category: '维修安装',
        title: '周末可帮邻居修小家电',
        description: '电饭煲、台灯等小问题可以帮忙看看，零件费另计。',
        expectedTime: '周末',
        location: '2号楼大堂',
        reward: '面议',
        icon: 'settings',
      },
    })
    expect(created.kind).toBe('提供')
    expect(created.place).toBe('2号楼大堂')
    expect(created.category).toBe('维修安装')

    const listed = await mockRequest<PageResult<ServicePost>>({
      url: '/services?kind=%E6%8F%90%E4%BE%9B&page=1&pageSize=50',
      method: 'GET',
    })
    expect(listed.list.some((post) => post.id === created.id)).toBe(true)
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

  it('registers a new user and completes onboarding', async () => {
    const phone = '13700001111'
    const result = await mockRequest<{
      isNewUser: boolean
      onboardingStatus: string
      profile: { nickname: string }
    }>({
      url: '/auth/login/sms',
      method: 'POST',
      data: { phone, code: '123456', intent: 'register', agreed: true },
    })
    expect(result.isNewUser).toBe(true)
    expect(result.onboardingStatus).toBe('NEW')
    expect(result.profile.nickname).toBe('邻居1111')

    const profile = await mockRequest<{ nickname: string; avatarPreset: string; onboardingStatus: string }>({
      url: '/auth/register/complete',
      method: 'POST',
      data: { nickname: '新邻居', avatarKey: 'avatar-person-2', intentCommunityId: 'c1' },
    })
    expect(profile.nickname).toBe('新邻居')
    expect(profile.avatarPreset).toBe('avatar-person-2')
    expect(profile.onboardingStatus).toBe('PROFILE_COMPLETED')

    const done = await mockRequest<{ onboardingStatus: string }>({
      url: '/auth/register/complete',
      method: 'POST',
      data: { finish: true },
    })
    expect(done.onboardingStatus).toBe('COMPLETED')
  })

  it('sends image messages and previews them in the conversation list', async () => {
    const created = await mockRequest<ChatMessage>({
      url: '/conversations/c1/messages',
      method: 'POST',
      data: {
        type: 'IMAGE',
        content: '',
        clientMsgId: 'mock-img-1',
        image: 'blob:mock-preview',
        extra: { width: 800, height: 600 },
      },
    })
    expect(created.type).toBe('IMAGE')
    expect(created.image).toBe('blob:mock-preview')
    expect(created.imageKey).toBe('blob:mock-preview')

    const conversations = await mockRequest<Conversation[]>({
      url: '/conversations',
      method: 'GET',
    })
    const target = conversations.find((item) => item.id === 'c1')
    expect(target?.lastMessage).toBe('[图片]')
    expect(target?.lastMessageType).toBe('IMAGE')

    const video = await mockRequest<ChatMessage>({
      url: '/conversations/c1/messages',
      method: 'POST',
      data: {
        type: 'VIDEO',
        content: '',
        clientMsgId: 'mock-video-1',
        image: 'blob:mock-video',
        extra: { duration: 12 },
      },
    })
    expect(video.type).toBe('VIDEO')
    const afterVideo = await mockRequest<Conversation[]>({
      url: '/conversations',
      method: 'GET',
    })
    expect(afterVideo.find((item) => item.id === 'c1')?.lastMessage).toBe('[视频]')
  })

  it('rejects login for an unregistered phone', async () => {
    await expect(
      mockRequest({
        url: '/auth/login/sms',
        method: 'POST',
        data: { phone: '13700002222', code: '123456', intent: 'login' },
      }),
    ).rejects.toMatchObject({ code: 40401 })
  })
})
