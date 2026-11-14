import * as communityApi from '../api/community.api'
import type { CommunityApplyPayload, CommunityBinding, CommunityVerifyResult } from '../models'

export const communityService = {
  getMine(): Promise<CommunityBinding[]> {
    return communityApi.getMyCommunities()
  },

  getNearby(): Promise<CommunityBinding[]> {
    return communityApi.getNearbyCommunities()
  },

  search(keyword: string): Promise<CommunityBinding[]> {
    return communityApi.searchCommunities(keyword)
  },

  verify(id: string, payload: CommunityApplyPayload): Promise<CommunityVerifyResult> {
    return communityApi.verifyCommunity(id, payload)
  },
}
