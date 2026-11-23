import * as communityApi from '../api/community.api'
import type { AddCommunityPayload, AddCommunityResult } from '../api/community.api'
import type {
  CommunityApplyPayload,
  CommunityBinding,
  CommunitySearchFilter,
  CommunityVerifyResult,
  RegionNode,
} from '../models'

export const communityService = {
  getMine(): Promise<CommunityBinding[]> {
    return communityApi.getMyCommunities()
  },

  getNearby(): Promise<CommunityBinding[]> {
    return communityApi.getNearbyCommunities()
  },

  search(filter: string | CommunitySearchFilter): Promise<CommunityBinding[]> {
    return communityApi.searchCommunities(filter)
  },

  getByRegion(regionId: string): Promise<CommunityBinding[]> {
    return communityApi.searchCommunities({ regionId })
  },

  getByStreet(streetId: string): Promise<CommunityBinding[]> {
    return communityApi.searchCommunities({ streetId })
  },

  getRegionChildren(parentId = ''): Promise<RegionNode[]> {
    return communityApi.getRegionChildren(parentId)
  },

  apply(payload: AddCommunityPayload): Promise<AddCommunityResult> {
    return communityApi.applyCommunity(payload)
  },

  verify(id: string, payload: CommunityApplyPayload): Promise<CommunityVerifyResult> {
    return communityApi.verifyCommunity(id, payload)
  },
}
