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
}

export interface CommunityApplyPayload {
  communityId: string
  identity: 'owner' | 'tenant' | 'family'
  building?: string
  images: string[]
}
