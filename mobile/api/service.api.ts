import type { PageResult, ServicePost, ServiceQuery } from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export function getServices(query: ServiceQuery = {}): Promise<PageResult<ServicePost>> {
  return get<PageResult<ServicePost>>(withQuery('/services', query))
}

export function createService(payload: Partial<ServicePost>): Promise<ServicePost> {
  return post<ServicePost>('/services', payload as Record<string, any>, { loading: true })
}

export function respondService(id: number | string): Promise<{ success: boolean; responses: number }> {
  return post<{ success: boolean; responses: number }>(`/services/${id}/respond`, {}, { idempotent: false })
}
