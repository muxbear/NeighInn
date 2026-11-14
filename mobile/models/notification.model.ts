import type { ZoneKey } from './item.model'

export type NotificationCategory = '交易' | '互动' | '社区'

export type NotificationRoute =
  | { type: 'item'; id: string }
  | { type: 'life'; id: string }
  | { type: 'broadcast'; id: string }
  | { type: 'zone'; zone: ZoneKey }
  | { type: 'messages' }
  | { type: 'order'; id: string }

export interface AppNotification {
  id: number
  category: NotificationCategory
  icon: string
  title: string
  description: string
  time: string
  createdAt: number
  tag: string
  route: NotificationRoute
  read: boolean
}

export interface NotificationSettings {
  pushEnabled: boolean
  tradeEnabled: boolean
  communityEnabled: boolean
  interactionEnabled: boolean
}

export type BroadcastTone = 'urgent' | 'free' | 'reward' | 'new'
export type BroadcastType = '紧急求助' | '免费上新' | '悬赏服务' | '新上架'

export interface BroadcastFact {
  icon: string
  label: string
  value: string
}

export interface BroadcastPublisher {
  id: string
  name: string
  avatar: string
  verified: boolean
}

export interface Broadcast {
  id: string
  type: BroadcastType
  icon: string
  title: string
  detail: string
  meta: string
  action: string
  tone: BroadcastTone
  facts?: BroadcastFact[]
  publisher?: BroadcastPublisher
  description?: string
  tip?: string
  responderAvatars?: string[]
  responseCount?: number
  favorited?: boolean
}
