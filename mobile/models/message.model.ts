import type { Item } from './item.model'

export type ChatMessageType = 'TEXT' | 'IMAGE' | 'ITEM' | 'SYSTEM'
export type ChatMessageStatus = 'SENDING' | 'SENT' | 'READ' | 'FAILED'

export interface ChatMessage {
  id: string
  clientMsgId?: string
  conversationId: string
  senderId: string
  senderName: string
  type: ChatMessageType
  content: string
  image?: string
  item?: Item
  createdAt: number
  timeText: string
  status: ChatMessageStatus
  mine: boolean
}

export interface Conversation {
  id: string
  peerId: string
  peerName: string
  peerAvatar: string
  peerVerified: boolean
  lastMessage: string
  lastTime: string
  unread: number
  itemId?: string
  muted?: boolean
}

export interface Friend {
  id: string
  name: string
  avatar: string
  verified: boolean
  community: string
  letter: string
  online?: boolean
}

export interface FriendRequest {
  id: string
  name: string
  avatar: string
  message: string
  time: string
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED'
}
