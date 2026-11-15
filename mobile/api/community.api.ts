import type {
  CommunityApplyPayload,
  CommunityBinding,
  CommunitySearchFilter,
  CommunityVerifyResult,
  RegionNode,
} from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export function getMyCommunities(): Promise<CommunityBinding[]> {
  return get<CommunityBinding[]>('/communities/mine')
}

export function getNearbyCommunities(): Promise<CommunityBinding[]> {
  return get<CommunityBinding[]>('/communities/nearby')
}

export function searchCommunities(filter: string | CommunitySearchFilter = ''): Promise<CommunityBinding[]> {
  const params = typeof filter === 'string' ? { keyword: filter } : filter
  return get<CommunityBinding[]>(withQuery('/communities/search', params))
}

export function getRegionChildren(parentId = ''): Promise<RegionNode[]> {
  return get<RegionNode[]>(withQuery('/regions/children', { parentId }))
}

export function verifyCommunity(id: string, payload: CommunityApplyPayload): Promise<CommunityVerifyResult> {
  return post<CommunityVerifyResult>(`/communities/${id}/verify`, payload as unknown as Record<string, any>, {
    loading: true,
  })
}
