import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ChatMessage, Conversation, Friend, FriendRequest } from '../models'
import { socialService } from '../services/social.service'
import { wsService } from '../services/ws.service'
import { uuidv4 } from '../utils/idempotency'
import { formatTime } from '../utils/formatter'

export const useSocialStore = defineStore('social', () => {
  const conversations = ref<Conversation[]>([])
  const friends = ref<Friend[]>([])
  const requests = ref<FriendRequest[]>([])
  const messagesByConv = ref<Record<string, ChatMessage[]>>({})
  const loading = ref(false)

  const unreadTotal = computed(() => conversations.value.reduce((sum, item) => sum + item.unread, 0))
  const pendingRequestCount = computed(() => requests.value.filter((item) => item.status === 'PENDING').length)

  async function fetchConversations(): Promise<void> {
    loading.value = true
    try {
      conversations.value = await socialService.getConversations()
    } finally {
      loading.value = false
    }
  }

  async function openConversation(peerId: string, itemId?: string): Promise<Conversation> {
    let conversation = conversations.value.find((entry) => entry.peerId === peerId)
    if (!conversation) {
      conversation = await socialService.createConversation(peerId, itemId)
      conversations.value = [conversation, ...conversations.value]
    }
    return conversation
  }

  async function fetchMessages(conversationId: string): Promise<ChatMessage[]> {
    const messages = await socialService.getMessages(conversationId)
    messagesByConv.value = { ...messagesByConv.value, [conversationId]: messages }
    return messages
  }

  async function sendMessage(conversationId: string, content: string): Promise<void> {
    const text = content.trim()
    if (!text) return
    const clientMsgId = uuidv4()
    const optimistic: ChatMessage = {
      id: `local-${clientMsgId}`,
      clientMsgId,
      conversationId,
      senderId: 'me',
      senderName: '我',
      type: 'TEXT',
      content: text,
      createdAt: Date.now(),
      timeText: formatTime(Date.now()),
      status: 'SENDING',
      mine: true,
    }
    const existing = messagesByConv.value[conversationId] ?? []
    messagesByConv.value = { ...messagesByConv.value, [conversationId]: [...existing, optimistic] }
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (conversation) {
      conversation.lastMessage = text
      conversation.lastTime = '刚刚'
    }
    wsService.sendMessage(conversationId, text, clientMsgId)

    try {
      const saved = await socialService.sendMessage(conversationId, text, { clientMsgId })
      replaceLocal(conversationId, optimistic.id, { ...saved, status: 'SENT' })
    } catch (error) {
      replaceLocal(conversationId, optimistic.id, { ...optimistic, status: 'FAILED' })
      throw error
    }
  }

  function replaceLocal(conversationId: string, localId: string, next: ChatMessage): void {
    const list = messagesByConv.value[conversationId] ?? []
    messagesByConv.value = {
      ...messagesByConv.value,
      [conversationId]: list.map((message) => (message.id === localId ? next : message)),
    }
  }

  async function markConversationRead(conversationId: string): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (conversation) conversation.unread = 0
    await socialService.readConversation(conversationId)
  }

  async function readAll(): Promise<void> {
    await socialService.readAll()
    conversations.value.forEach((item) => {
      item.unread = 0
    })
  }

  async function fetchFriends(): Promise<void> {
    friends.value = await socialService.getFriends()
  }

  async function fetchRequests(): Promise<void> {
    requests.value = await socialService.getFriendRequests()
  }

  async function acceptRequest(id: string): Promise<void> {
    await socialService.acceptRequest(id)
    const request = requests.value.find((item) => item.id === id)
    if (request) request.status = 'ACCEPTED'
    await fetchFriends()
  }

  async function rejectRequest(id: string): Promise<void> {
    await socialService.rejectRequest(id)
    const request = requests.value.find((item) => item.id === id)
    if (request) request.status = 'REJECTED'
  }

  function applyIncomingMessage(message: ChatMessage): void {
    const list = messagesByConv.value[message.conversationId] ?? []
    if (list.some((item) => item.id === message.id)) return
    messagesByConv.value = {
      ...messagesByConv.value,
      [message.conversationId]: [...list, message],
    }
    const conversation = conversations.value.find((item) => item.id === message.conversationId)
    if (conversation) {
      conversation.lastMessage = message.content
      conversation.lastTime = message.timeText
      conversation.unread += 1
    }
  }

  return {
    conversations,
    friends,
    requests,
    messagesByConv,
    loading,
    unreadTotal,
    pendingRequestCount,
    fetchConversations,
    openConversation,
    fetchMessages,
    sendMessage,
    markConversationRead,
    readAll,
    fetchFriends,
    fetchRequests,
    acceptRequest,
    rejectRequest,
    applyIncomingMessage,
  }
})
