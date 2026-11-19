import type {
  BlockedPage,
  ChatMessage,
  Conversation,
  Friend,
  FriendRequest,
  NeighborPage,
  NeighborRelation,
  SocialEligibility,
} from '../models'
import { del, get, post, put } from './request'

export function getConversations(): Promise<Conversation[]> {
  return get<Conversation[]>('/conversations')
}

export function createConversation(payload: { peerId: string; itemId?: string }): Promise<Conversation> {
  return post<Conversation>('/conversations', payload)
}

export function getMessages(
  conversationId: string,
  params: { beforeSeq?: number; afterSeq?: number; limit?: number } = {},
): Promise<{ items: ChatMessage[]; hasMoreBefore: boolean; hasMoreAfter: boolean }> {
  return get(`/conversations/${conversationId}/messages`, params)
}

export function sendMessage(
  conversationId: string,
  payload: {
    content: string
    type?: string
    clientMsgId?: string
    image?: string
    extra?: Record<string, any>
  },
): Promise<ChatMessage> {
  return post<ChatMessage>(`/conversations/${conversationId}/messages`, payload, { idempotent: false })
}

export function readConversation(
  conversationId: string,
  lastSeq: number,
): Promise<{ success: boolean; lastSeq: number }> {
  return post(`/conversations/${conversationId}/read`, { lastSeq }, { idempotent: false })
}

export function readAllConversations(): Promise<{ success: boolean }> {
  return post('/conversations/read-all', {}, { idempotent: false })
}

export function getEligibility(): Promise<SocialEligibility> {
  return get<SocialEligibility>('/friends/eligibility')
}

export function getFriends(params: {
  keyword?: string
  building?: string
  page?: number
  pageSize?: number
} = {}): Promise<NeighborPage> {
  return get<NeighborPage>('/friends', params)
}

export function getNeighbor(peerId: string): Promise<NeighborRelation> {
  return get<NeighborRelation>(`/friends/${peerId}`)
}

export function setRemark(peerId: string, remark: string): Promise<{ peerId: string; remark: string }> {
  return put(`/friends/${peerId}/remark`, { remark })
}

export function blockPeer(
  peerId: string,
  payload: { reason?: string; source?: string } = {},
): Promise<{ blocked: boolean }> {
  return post(`/friends/${peerId}/block`, payload)
}

export function unblockPeer(peerId: string): Promise<{ blocked: boolean }> {
  return del(`/friends/${peerId}/block`)
}

export function getBlocks(page = 1, pageSize = 20): Promise<BlockedPage> {
  return get<BlockedPage>('/friends/blocks', { page, pageSize })
}

export function getFriendRequests(): Promise<FriendRequest[]> {
  return get<FriendRequest[]>('/friends/requests')
}

export function sendFriendRequest(payload: { name: string; message: string }): Promise<FriendRequest> {
  return post<FriendRequest>('/friends/requests', payload)
}

export function acceptFriendRequest(id: string): Promise<{ success: boolean }> {
  return post(`/friends/requests/${id}/accept`, {})
}

export function rejectFriendRequest(id: string): Promise<{ success: boolean }> {
  return post(`/friends/requests/${id}/reject`, {})
}

export function deleteFriend(id: string): Promise<{ success: boolean }> {
  return del(`/friends/${id}`)
}

export type { Friend }
