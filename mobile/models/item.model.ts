import type { PageQuery } from './common.model'

export type TradeType = '出售' | '免费' | '互换'
export type TradeTypeCode = 'MONETARY' | 'FREE_GIFT' | 'BARTER'
export type ZoneKey = 'gift' | 'swap' | 'sale' | 'service'
export type ItemStatus = 'DRAFT' | 'AUDITING' | 'ON_SALE' | 'RESERVED' | 'OFF_SHELF' | 'REJECTED' | 'SOLD'

export interface SellerSummary {
  id: string
  name: string
  avatar: string
  credit: string
  dealCount: number
  area: string
  verified: boolean
  joinedDays?: number
  following?: boolean
  /** 邻里等级：1–9，体现交易与互助活跃度 */
  level?: number
}

export interface Item {
  id: string
  title: string
  price: number | string
  type: TradeType
  condition: string
  distance: string
  walk: string
  time: string
  image: string
  images?: string[]
  community?: string
  gallery?: string[]
  barterExpect?: string
  description?: string
  seller?: SellerSummary
  aiVerified?: boolean
  status?: ItemStatus
  favorite?: boolean
  category?: string
  createdAt?: number
  viewCount?: number
  commentCount?: number
  tradeTypeCode?: TradeTypeCode
}

export interface ItemComment {
  id: string
  author: string
  avatar: string
  time: string
  content: string
  replyTo?: string
}

export interface ItemQuery extends PageQuery {
  zone?: ZoneKey
  type?: TradeType
  category?: string
  keyword?: string
  sort?: string
  communityId?: string
  near?: boolean
}

export interface ItemDraft {
  images: string[]
  title: string
  tradeType: TradeType
  price: string
  barterExpect: string
  condition: string
  category: string
  qualityDesc: string
  videoUrl?: string
  invoices?: string[]
  expectTime?: string
}

export interface CreateItemResult {
  id: string
  status: ItemStatus
}

export interface ZoneStat {
  key: ZoneKey
  name: string
  count: number
}
