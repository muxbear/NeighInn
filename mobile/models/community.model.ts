export interface CommunitySummary {
  id: string
  name: string
  building: string
  verifiedCount: number
  itemCount: number
  serviceCount: number
}

export type CommunityRole = '业主' | '租户' | '家属'
export type CommunityVerifyStatus = '已认证' | '审核中' | '已驳回'

/** 行政区划节点：省份/直辖市 → 地市 → 区/县 → 街道 */
export interface RegionNode {
  id: string
  name: string
  level: 'PROVINCE' | 'CITY' | 'DISTRICT' | 'STREET'
  code?: string
}

export interface CommunitySearchFilter {
  keyword?: string
  cityId?: string
  streetId?: string
  regionId?: string
}

export interface CommunityBinding {
  id: string
  name: string
  building?: string
  role: CommunityRole
  status: CommunityVerifyStatus
  memberCount: number
  itemCount: number
  helpCount: number
  distance?: string
  address?: string
  province?: string
  city?: string
  district?: string
  street?: string
  regionPath?: string
  regionId?: string
  streetId?: string
}

export interface CommunityApplyPayload {
  communityId: string
  identity: 'owner' | 'tenant' | 'family'
  building?: string
  images: string[]
}
