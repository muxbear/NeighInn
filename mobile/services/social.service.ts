import * as socialApi from '../api/social.api'
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

export const socialService = {
  getConversations(): Promise<Conversation[]> {
    return socialApi.getConversations()
  },

  createConversation(peerId: string, itemId?: string): Promise<Conversation> {
    return socialApi.createConversation({ peerId, itemId })
  },

  getMessages(
    conversationId: string,
    params: { beforeSeq?: number; afterSeq?: number; limit?: number } = {},
  ): Promise<{ items: ChatMessage[]; hasMoreBefore: boolean; hasMoreAfter: boolean }> {
    return socialApi.getMessages(conversationId, params)
  },

  sendMessage(
    conversationId: string,
    content: string,
    options: { type?: string; clientMsgId?: string; image?: string; extra?: Record<string, any> } = {},
  ): Promise<ChatMessage> {
    return socialApi.sendMessage(conversationId, {
      content,
      type: options.type ?? 'TEXT',
      clientMsgId: options.clientMsgId,
      image: options.image,
      extra: options.extra,
    })
  },

  readConversation(conversationId: string, lastSeq: number): Promise<{ success: boolean; lastSeq: number }> {
    return socialApi.readConversation(conversationId, lastSeq)
  },

  readAll(): Promise<{ success: boolean }> {
    return socialApi.readAllConversations()
  },

  getEligibility(): Promise<SocialEligibility> {
    return socialApi.getEligibility()
  },

  getFriends(params: {
    keyword?: string
    building?: string
    page?: number
    pageSize?: number
  } = {}): Promise<NeighborPage> {
    return socialApi.getFriends(params)
  },

  getNeighbor(peerId: string): Promise<NeighborRelation> {
    return socialApi.getNeighbor(peerId)
  },

  setRemark(peerId: string, remark: string): Promise<{ peerId: string; remark: string }> {
    return socialApi.setRemark(peerId, remark)
  },

  blockPeer(peerId: string, reason = '', source = 'CHAT'): Promise<{ blocked: boolean }> {
    return socialApi.blockPeer(peerId, { reason, source })
  },

  unblockPeer(peerId: string): Promise<{ blocked: boolean }> {
    return socialApi.unblockPeer(peerId)
  },

  getBlocks(page = 1, pageSize = 20): Promise<BlockedPage> {
    return socialApi.getBlocks(page, pageSize)
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

export type { Friend }
