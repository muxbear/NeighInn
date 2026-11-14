import type { Item } from './item.model'
import type { LifePost } from './life.model'
import type { ServicePost } from './service.model'

export interface CategoryBundle {
  itemCategories: string[]
  conditions: string[]
  lifeCategories: string[]
  serviceCategories: string[]
}

export interface SearchResult {
  keyword: string
  items: Item[]
  lifePosts: LifePost[]
  services: ServicePost[]
}

export interface FavoriteBundle {
  items: Item[]
  services: ServicePost[]
  life: LifePost[]
}

export interface UnreadSummary {
  count: number
  conversationCount: number
}

export interface AvatarPresetGroup {
  key: string
  label: string
  items: string[]
}

export interface CreditRecord {
  id: string
  title: string
  delta: number
  time: string
}

export interface CreditInfo {
  score: number
  level: string
  nextLevel: string
  records: CreditRecord[]
}

export interface MineStats {
  publishCount: number
  favoriteCount: number
  historyCount: number
  lifeCount: number
  serviceCount: number
  creditScore: number
}

export interface PaymentPrepayResult {
  orderNo: string
  orderId: string
  payParams: Record<string, any>
  expireAt: number
}

export interface PaymentStatusResult {
  status: 'SUCCESS' | 'PROCESSING' | 'FAILED' | 'NOT_FOUND'
  orderId?: string
  orderStatus?: string
}

export interface AuditSubmitResult {
  auditId: string
  status: string
}

export interface CommunityVerifyResult {
  status: string
  success: boolean
}

export interface PresignResult {
  uploadUrl: string
  fileUrl: string
  headers: Record<string, string>
}

export interface DistanceInfo {
  distance: string
  walk: string
  bike: string
  car: string
  meters: number
}
