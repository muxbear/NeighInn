import type { PageResult, ServiceKind, ServicePost, ServiceQuery } from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export interface CreateServiceInput {
  kind: ServiceKind
  category: string
  title: string
  description?: string
  expectedTime?: string
  location?: string
  reward?: string
  icon?: string
  media?: string[]
  mediaType?: 'GALLERY' | 'VIDEO'
  coverKey?: string
}

export function getServices(query: ServiceQuery = {}): Promise<PageResult<ServicePost>> {
  return get<PageResult<ServicePost>>(withQuery('/services', query))
}

export function createService(payload: CreateServiceInput): Promise<ServicePost> {
  // 服务端使用 HELP/OFFER 枚举，移动端展示层统一使用「求助/提供」。
  const body = {
    kind: payload.kind === '提供' ? 'OFFER' : 'HELP',
    category: payload.category,
    title: payload.title,
    description: payload.description ?? '',
    expectedTime: payload.expectedTime ?? '',
    location: payload.location ?? '',
    reward: payload.reward ?? '',
    icon: payload.icon ?? '',
    media: payload.media ?? [],
    mediaType: payload.mediaType ?? 'GALLERY',
    coverKey: payload.coverKey ?? '',
  }
  return post<ServicePost>('/services', body, { loading: true })
}

export function respondService(id: number | string): Promise<{ success: boolean; responses: number }> {
  return post<{ success: boolean; responses: number }>(`/services/${id}/respond`, {}, { idempotent: false })
}
