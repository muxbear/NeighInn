import type { CommunityApplyPayload, CommunityBinding, CommunityVerifyResult } from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export function getMyCommunities(): Promise<CommunityBinding[]> {
  return get<CommunityBinding[]>('/communities/mine')
}

export function getNearbyCommunities(): Promise<CommunityBinding[]> {
  return get<CommunityBinding[]>('/communities/nearby')
}

export function searchCommunities(keyword: string): Promise<CommunityBinding[]> {
  return get<CommunityBinding[]>(withQuery('/communities/search', { keyword }))
}

export function verifyCommunity(id: string, payload: CommunityApplyPayload): Promise<CommunityVerifyResult> {
  return post<CommunityVerifyResult>(`/communities/${id}/verify`, payload as unknown as Record<string, any>, {
    loading: true,
  })
}
