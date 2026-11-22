import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  BlockedUser,
  ChatMessage,
  Conversation,
  Friend,
  FriendRequest,
  SocialEligibility,
} from '../models'
import { socialService } from '../services/social.service'
import { wsService } from '../services/ws.service'
import { uuidv4 } from '../utils/idempotency'
import { formatTime } from '../utils/formatter'

function sortMessages(list: ChatMessage[]): ChatMessage[] {
  return [...list].sort((a, b) => {
    const aSeq = (a.seq ?? 0) > 0 ? (a.seq ?? 0) : Number.MAX_SAFE_INTEGER
    const bSeq = (b.seq ?? 0) > 0 ? (b.seq ?? 0) : Number.MAX_SAFE_INTEGER
    if (aSeq !== bSeq) return aSeq - bSeq
    return a.createdAt - b.createdAt
  })
}

function dedupeMessages(list: ChatMessage[]): ChatMessage[] {
  const seenIds = new Set<string>()
  const seenClients = new Set<string>()
  const result: ChatMessage[] = []
  for (const message of sortMessages(list)) {
    if (message.id && seenIds.has(message.id)) continue
    if (message.clientMsgId && seenClients.has(message.clientMsgId)) continue
    if (message.id) seenIds.add(message.id)
    if (message.clientMsgId) seenClients.add(message.clientMsgId)
    result.push(message)
  }
  return result
}

const MEDIA_MESSAGE_TYPES = ['IMAGE', 'VIDEO']

function isMediaType(type: string): boolean {
  return MEDIA_MESSAGE_TYPES.indexOf(type) >= 0
}

/** 会话列表预览文案：媒体消息没有文本，使用固定占位。 */
function previewOf(type: string, content: string): string {
  if (type === 'IMAGE') return '[图片]'
  if (type === 'VIDEO') return '[视频]'
  if (type === 'EMOJI') return '[表情]'
  return content
}

export const useSocialStore = defineStore('social', () => {
  const conversations = ref<Conversation[]>([])
  const neighbors = ref<Friend[]>([])
  const requests = ref<FriendRequest[]>([])
  const blocks = ref<BlockedUser[]>([])
  const eligibility = ref<SocialEligibility | null>(null)
  const messagesByConv = ref<Record<string, ChatMessage[]>>({})
  const lastSeqByConv = ref<Record<string, number>>({})
  const loading = ref(false)
  const neighborLoading = ref(false)
  const neighborHasMore = ref(false)
  const neighborTotal = ref(0)
  const neighborPage = ref(1)
  const neighborKeyword = ref('')
  const neighborBuilding = ref('')

  // 兼容旧页面：friends 为邻居列表的只读投影。
  const friends = computed(() => neighbors.value)
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

  async function fetchEligibility(): Promise<SocialEligibility> {
    eligibility.value = await socialService.getEligibility()
    return eligibility.value
  }

  async function fetchNeighbors(reset = false): Promise<void> {
    if (neighborLoading.value) return
    if (reset) {
      neighborPage.value = 1
      neighborHasMore.value = false
    }
    neighborLoading.value = true
    try {
      const page = await socialService.getFriends({
        keyword: neighborKeyword.value,
        building: neighborBuilding.value,
        page: neighborPage.value,
        pageSize: 50,
      })
      eligibility.value = page.eligibility
      neighbors.value = reset ? page.items : dedupeFriends([...neighbors.value, ...page.items])
      neighborTotal.value = page.total
      neighborHasMore.value = page.hasMore
      if (page.hasMore) neighborPage.value += 1
    } finally {
      neighborLoading.value = false
    }
  }

  function dedupeFriends(list: Friend[]): Friend[] {
    const map = new Map<string, Friend>()
    list.forEach((friend) => map.set(friend.userId || friend.id, friend))
    return [...map.values()]
  }

  async function fetchFriends(): Promise<void> {
    await fetchNeighbors(true)
  }

  async function loadMoreNeighbors(): Promise<void> {
    if (!neighborHasMore.value || neighborLoading.value) return
    await fetchNeighbors(false)
  }

  async function setNeighborFilter(keyword: string, building = ''): Promise<void> {
    neighborKeyword.value = keyword
    neighborBuilding.value = building
    await fetchNeighbors(true)
  }

  async function fetchRequests(): Promise<void> {
    requests.value = await socialService.getFriendRequests()
  }

  async function fetchBlocks(): Promise<void> {
    const page = await socialService.getBlocks(1, 50)
    blocks.value = page.items
  }

  async function blockPeer(peerId: string, reason = ''): Promise<void> {
    await socialService.blockPeer(peerId, reason, 'CHAT')
    neighbors.value = neighbors.value.filter((item) => (item.userId || item.id) !== peerId)
    conversations.value = conversations.value.filter((item) => item.peerId !== peerId)
    blocks.value = blocks.value.filter((item) => item.userId !== peerId)
  }

  async function unblockPeer(peerId: string): Promise<void> {
    await socialService.unblockPeer(peerId)
    blocks.value = blocks.value.filter((item) => item.userId !== peerId)
    await fetchNeighbors(true)
  }

  async function setRemark(peerId: string, remark: string): Promise<void> {
    await socialService.setRemark(peerId, remark)
    const target = neighbors.value.find((item) => (item.userId || item.id) === peerId)
    if (target) {
      target.remark = remark
      target.name = remark || target.name
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

  async function fetchMessages(conversationId: string, beforeSeq?: number): Promise<ChatMessage[]> {
    const page = await socialService.getMessages(conversationId, {
      beforeSeq,
      limit: 30,
    })
    const existing = messagesByConv.value[conversationId] ?? []
    const merged = beforeSeq ? [...page.items, ...existing] : [...existing, ...page.items]
    messagesByConv.value = {
      ...messagesByConv.value,
      [conversationId]: dedupeMessages(merged),
    }
    const seqs = page.items.map((item) => item.seq ?? 0).filter((seq) => seq > 0)
    if (seqs.length) {
      lastSeqByConv.value = {
        ...lastSeqByConv.value,
        [conversationId]: Math.max(lastSeqByConv.value[conversationId] ?? 0, ...seqs),
      }
    }
    return messagesByConv.value[conversationId]
  }

  async function sendMessage(
    conversationId: string,
    content: string,
    options: {
      type?: string
      extra?: Record<string, any>
      /** 已上传的媒体对象键（IMAGE / VIDEO） */
      image?: string
      /** 本地临时路径，用于乐观气泡即时展示 */
      localPreview?: string
    } = {},
  ): Promise<void> {
    const text = content.trim()
    const type = options.type ?? 'TEXT'
    const media = isMediaType(type)
    const image = options.image ?? ''
    if (media ? !image : !text) return
    const clientMsgId = uuidv4()
    const optimistic: ChatMessage = {
      id: `local-${clientMsgId}`,
      clientMsgId,
      conversationId,
      seq: 0,
      senderId: 'me',
      senderName: '我',
      type: type as ChatMessage['type'],
      content: text,
      image: options.localPreview || image || undefined,
      imageKey: image || undefined,
      extra: options.extra,
      createdAt: Date.now(),
      timeText: formatTime(Date.now()),
      status: 'SENDING',
      mine: true,
    }
    const existing = messagesByConv.value[conversationId] ?? []
    messagesByConv.value = {
      ...messagesByConv.value,
      [conversationId]: sortMessages([...existing, optimistic]),
    }
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (conversation) {
      conversation.lastMessage = previewOf(type, text)
      conversation.lastMessageType = type
      conversation.lastTime = '刚刚'
    }

    // HTTP 作为权威发送通道，保证失败可重试；WebSocket 负责实时下行推送。
    try {
      const saved = await socialService.sendMessage(conversationId, text, {
        type,
        clientMsgId,
        image: image || undefined,
        extra: options.extra,
      })
      replaceLocal(conversationId, optimistic.id, { ...saved, status: 'SENT', mine: true })
    } catch (error) {
      replaceLocal(conversationId, optimistic.id, { ...optimistic, status: 'FAILED' })
      throw error
    }
  }

  async function resendMessage(conversationId: string, message: ChatMessage): Promise<void> {
    if (!message.clientMsgId) return
    const media = isMediaType(message.type)
    if (media && !message.imageKey) {
      throw new Error('媒体文件已失效，请重新选择后发送')
    }
    const updated = { ...message, status: 'SENDING' as const }
    replaceLocal(conversationId, message.id, updated)
    try {
      const saved = await socialService.sendMessage(conversationId, message.content, {
        type: message.type,
        clientMsgId: message.clientMsgId,
        image: media ? message.imageKey : undefined,
        extra: message.extra,
      })
      replaceLocal(conversationId, message.id, { ...saved, status: 'SENT', mine: true })
    } catch (error) {
      replaceLocal(conversationId, message.id, { ...updated, status: 'FAILED' })
      throw error
    }
  }

  function replaceLocal(conversationId: string, localId: string, next: ChatMessage): void {
    const list = messagesByConv.value[conversationId] ?? []
    messagesByConv.value = {
      ...messagesByConv.value,
      [conversationId]: dedupeMessages(
        list.map((message) => (message.id === localId ? next : message)),
      ),
    }
  }

  function applyAck(payload: any): void {
    if (!payload?.clientMsgId) return
    const message: ChatMessage | undefined = payload.message
    Object.keys(messagesByConv.value).forEach((conversationId) => {
      const list = messagesByConv.value[conversationId]
      const target = list.find(
        (item) => item.clientMsgId === payload.clientMsgId && item.status !== 'SENT',
      )
      if (!target) return
      const next: ChatMessage = message
        ? { ...message, mine: true, status: 'SENT' }
        : {
            ...target,
            id: payload.messageId || target.id,
            seq: Number(payload.seq) || target.seq || 0,
            createdAt: Number(payload.createdAt) || target.createdAt,
            status: 'SENT',
          }
      replaceLocal(conversationId, target.id, next)
    })
  }

  async function markConversationRead(conversationId: string): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === conversationId)
    const list = messagesByConv.value[conversationId] ?? []
    const lastSeq = list.reduce((max, item) => Math.max(max, item.seq || 0), 0)
    if (conversation) conversation.unread = 0
    if (lastSeq <= 0) return
    lastSeqByConv.value = { ...lastSeqByConv.value, [conversationId]: lastSeq }
    wsService.markRead(conversationId, lastSeq)
    await socialService.readConversation(conversationId, lastSeq)
  }

  async function readAll(): Promise<void> {
    await socialService.readAll()
    conversations.value.forEach((item) => {
      item.unread = 0
    })
  }

  async function acceptRequest(id: string): Promise<void> {
    await socialService.acceptRequest(id)
    const request = requests.value.find((item) => item.id === id)
    if (request) request.status = 'ACCEPTED'
    await fetchNeighbors(true)
  }

  async function rejectRequest(id: string): Promise<void> {
    await socialService.rejectRequest(id)
    const request = requests.value.find((item) => item.id === id)
    if (request) request.status = 'REJECTED'
  }

  function applyIncomingMessage(message: ChatMessage): void {
    const conversationId = message.conversationId
    const list = messagesByConv.value[conversationId] ?? []
    if (list.some((item) => item.id === message.id)) return
    if (message.clientMsgId && list.some((item) => item.clientMsgId === message.clientMsgId)) return
    messagesByConv.value = {
      ...messagesByConv.value,
      [conversationId]: dedupeMessages([...list, message]),
    }
    lastSeqByConv.value = {
      ...lastSeqByConv.value,
      [conversationId]: Math.max(lastSeqByConv.value[conversationId] ?? 0, message.seq || 0),
    }
    const conversation = conversations.value.find((item) => item.id === conversationId)
    if (conversation) {
      conversation.lastMessage = previewOf(message.type, message.content)
      conversation.lastMessageType = message.type
      conversation.lastTime = message.timeText || formatTime(message.createdAt)
      conversation.unread += 1
    } else {
      fetchConversations().catch(() => undefined)
    }
  }

  function applyRelationChanged(peerId: string, state: string): void {
    if (state === 'BLOCKED') {
      neighbors.value = neighbors.value.filter((item) => (item.userId || item.id) !== peerId)
      conversations.value = conversations.value.filter((item) => item.peerId !== peerId)
    } else {
      fetchNeighbors(true).catch(() => undefined)
      fetchConversations().catch(() => undefined)
    }
  }

  return {
    conversations,
    neighbors,
    friends,
    requests,
    blocks,
    eligibility,
    messagesByConv,
    lastSeqByConv,
    loading,
    neighborLoading,
    neighborHasMore,
    neighborTotal,
    neighborKeyword,
    neighborBuilding,
    unreadTotal,
    pendingRequestCount,
    fetchConversations,
    fetchEligibility,
    fetchNeighbors,
    fetchFriends,
    loadMoreNeighbors,
    setNeighborFilter,
    fetchRequests,
    fetchBlocks,
    blockPeer,
    unblockPeer,
    setRemark,
    openConversation,
    fetchMessages,
    sendMessage,
    resendMessage,
    applyAck,
    markConversationRead,
    readAll,
    acceptRequest,
    rejectRequest,
    applyIncomingMessage,
    applyRelationChanged,
  }
})
