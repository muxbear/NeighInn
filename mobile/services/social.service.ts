import * as socialApi from '../api/social.api'
import type { ChatMessage, Conversation, Friend, FriendRequest } from '../models'

export const socialService = {
  getConversations(): Promise<Conversation[]> {
    return socialApi.getConversations()
  },

  createConversation(peerId: string, itemId?: string): Promise<Conversation> {
    return socialApi.createConversation({ peerId, itemId })
  },

  getMessages(conversationId: string): Promise<ChatMessage[]> {
    return socialApi.getMessages(conversationId)
  },

  sendMessage(
    conversationId: string,
    content: string,
    options: { type?: string; clientMsgId?: string; image?: string } = {},
  ): Promise<ChatMessage> {
    return socialApi.sendMessage(conversationId, {
      content,
      type: options.type ?? 'TEXT',
      clientMsgId: options.clientMsgId,
      image: options.image,
    })
  },

  readConversation(conversationId: string): Promise<{ success: boolean }> {
    return socialApi.readConversation(conversationId)
  },

  readAll(): Promise<{ success: boolean }> {
    return socialApi.readAllConversations()
  },

  getFriends(): Promise<Friend[]> {
    return socialApi.getFriends()
  },

  getFriendRequests(): Promise<FriendRequest[]> {
    return socialApi.getFriendRequests()
  },

  sendFriendRequest(name: string, message: string): Promise<FriendRequest> {
    return socialApi.sendFriendRequest({ name, message })
  },

  acceptRequest(id: string): Promise<{ success: boolean }> {
    return socialApi.acceptFriendRequest(id)
  },

  rejectRequest(id: string): Promise<{ success: boolean }> {
    return socialApi.rejectFriendRequest(id)
  },

  deleteFriend(id: string): Promise<{ success: boolean }> {
    return socialApi.deleteFriend(id)
  },
}
