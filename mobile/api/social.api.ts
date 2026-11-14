import type { ChatMessage, Conversation, Friend, FriendRequest } from '../models'
import { del, get, post } from './request'

export function getConversations(): Promise<Conversation[]> {
  return get<Conversation[]>('/conversations')
}

export function createConversation(payload: { peerId: string; itemId?: string }): Promise<Conversation> {
  return post<Conversation>('/conversations', payload)
}

export function getMessages(conversationId: string): Promise<ChatMessage[]> {
  return get<ChatMessage[]>(`/conversations/${conversationId}/messages`)
}

export function sendMessage(
  conversationId: string,
  payload: { content: string; type?: string; clientMsgId?: string; image?: string },
): Promise<ChatMessage> {
  return post<ChatMessage>(`/conversations/${conversationId}/messages`, payload, { idempotent: false })
}

export function readConversation(conversationId: string): Promise<{ success: boolean }> {
  return post(`/conversations/${conversationId}/read`, {}, { idempotent: false })
}

export function readAllConversations(): Promise<{ success: boolean }> {
  return post('/conversations/read-all', {}, { idempotent: false })
}

export function getFriends(): Promise<Friend[]> {
  return get<Friend[]>('/friends')
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
