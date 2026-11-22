import type { Item } from './item.model'

export type ChatMessageType = 'TEXT' | 'EMOJI' | 'IMAGE' | 'VIDEO' | 'VOICE' | 'ITEM' | 'SYSTEM'
export type ChatMessageStatus = 'SENDING' | 'SENT' | 'READ' | 'FAILED'

export interface ChatMessage {
  id: string
  clientMsgId?: string
  conversationId: string
  /** 服务端会话内序号；本地乐观消息可为空 */
  seq?: number
  senderId: string
  senderName: string
  senderAvatar?: string
  type: ChatMessageType
  content: string
  /** 可直接展示/播放的媒体地址（服务端下发签名 URL，本地乐观消息为临时路径） */
  image?: string
  /** 媒体对象键，重发时使用 */
  imageKey?: string
  item?: Item
  extra?: Record<string, any>
  createdAt: number
  timeText: string
  status: ChatMessageStatus
  mine: boolean
  riskFlag?: string | null
}

export interface Conversation {
  id: string
  /** 好友会话 / 物品会话；Mock 数据可能缺省 */
  type?: 'FRIEND' | 'ITEM'
  peerId: string
  peerName: string
  peerAvatar: string
  peerVerified: boolean
  peerCommunity?: string
  lastMessage: string
  lastMessageType?: string
  lastTime: string
  unread: number
  itemId?: string
  muted?: boolean
  canSend?: boolean
  readOnlyReason?: 'BLOCKED' | 'INELIGIBLE' | string | null
}

export interface Friend {
  id: string
  /** 服务端用户 ID；Mock 数据可能只提供 id */
  userId?: string
  name: string
  avatar: string
  remark?: string
  verified: boolean
  community: string
  building?: string
  identityType?: string
  letter: string
  online?: boolean
}

export interface SocialEligibility {
  eligible: boolean
  realnameVerified: boolean
  ownerVerified: boolean
  communityId?: string | null
  communityName?: string
  reasonCode: 'OK' | 'REALNAME_REQUIRED' | 'OWNER_PROOF_REQUIRED' | 'COMMUNITY_INACTIVE' | string
  reasonText?: string
}

export interface NeighborPage {
  items: Friend[]
  page: number
  pageSize: number
  total: number
  hasMore: boolean
  eligibility: SocialEligibility
}

export interface BlockedUser {
  userId: string
  name: string
  avatar: string
  reason: string
  blockedAt: number
}

export interface BlockedPage {
  items: BlockedUser[]
  page: number
  pageSize: number
  total: number
  hasMore: boolean
}

export interface NeighborRelation {
  userId: string
  name: string
  avatar: string
  remark: string
  community: string
  building: string
  identityType: string
  relation: 'FRIEND' | 'SELF' | 'ME_NOT_ELIGIBLE' | 'PEER_NOT_ELIGIBLE' | 'NOT_SAME_COMMUNITY' | 'BLOCKED'
  blockedByMe: boolean
  blockedMe: boolean
  canMessage: boolean
  reasonCode: string
}

export interface FriendRequest {
  id: string
  name: string
  avatar: string
  message: string
  time: string
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED'
}
