import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../services/social.service', () => ({
  socialService: {
    getConversations: vi.fn(),
    getEligibility: vi.fn(),
    getFriends: vi.fn(),
    getBlocks: vi.fn(),
    blockPeer: vi.fn(),
    unblockPeer: vi.fn(),
    setRemark: vi.fn(),
    createConversation: vi.fn(),
    getMessages: vi.fn(),
    sendMessage: vi.fn(),
    readConversation: vi.fn(),
    readAll: vi.fn(),
    getFriendRequests: vi.fn(),
    acceptRequest: vi.fn(),
    rejectRequest: vi.fn(),
  },
}))

vi.mock('../../services/ws.service', () => ({
  wsService: {
    isConnected: () => false,
    sendMessage: vi.fn(),
    markRead: vi.fn(),
  },
}))

import type { ChatMessage, Conversation, Friend } from '../../models'
import { socialService } from '../../services/social.service'
import { useSocialStore } from '../../stores/social.store'

function message(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: 'm1',
    conversationId: 'c1',
    seq: 1,
    senderId: 'u1',
    senderName: '邻居',
    type: 'TEXT',
    content: '你好',
    createdAt: Date.now(),
    timeText: '刚刚',
    status: 'SENT',
    mine: false,
    ...overrides,
  }
}

describe('social store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('deduplicates incoming messages by id and sorts by seq', () => {
    const store = useSocialStore()
    store.applyIncomingMessage(message({ id: 'm2', seq: 2, content: '第二条' }))
    store.applyIncomingMessage(message({ id: 'm1', seq: 1, content: '第一条' }))
    store.applyIncomingMessage(message({ id: 'm2', seq: 2, content: '第二条' }))
    expect(store.messagesByConv.c1.map((item) => item.id)).toEqual(['m1', 'm2'])
    expect(store.lastSeqByConv.c1).toBe(2)
  })

  it('sends media messages without text and keeps the server media URL', async () => {
    const store = useSocialStore()
    const conversation: Conversation = {
      id: 'c1',
      type: 'FRIEND',
      peerId: 'u1',
      peerName: '邻居',
      peerAvatar: 'avatar-person-1',
      peerVerified: true,
      lastMessage: '你好',
      lastTime: '刚刚',
      unread: 0,
      canSend: true,
    }
    store.conversations = [conversation]
    const send = vi.mocked(socialService.sendMessage)
    send.mockResolvedValueOnce(message({
      id: 'srv-1',
      type: 'IMAGE',
      content: '',
      image: '/api/v1/media/private/chat/chat_image/1/a.jpg?e=1&s=x',
      imageKey: 'chat/chat_image/1/a.jpg',
      mine: true,
      status: 'SENT',
    }))

    await store.sendMessage('c1', '', {
      type: 'IMAGE',
      image: 'chat/chat_image/1/a.jpg',
      localPreview: 'blob:local-preview',
      extra: { width: 800, height: 600 },
    })

    expect(send).toHaveBeenCalledWith('c1', '', expect.objectContaining({
      type: 'IMAGE',
      image: 'chat/chat_image/1/a.jpg',
      extra: { width: 800, height: 600 },
    }))
    const list = store.messagesByConv.c1
    expect(list).toHaveLength(1)
    expect(list[0].image).toContain('/api/v1/media/private/')
    expect(list[0].imageKey).toBe('chat/chat_image/1/a.jpg')
    expect(store.conversations[0].lastMessage).toBe('[图片]')
    expect(store.conversations[0].lastMessageType).toBe('IMAGE')
  })

  it('resends media with the uploaded key and rejects messages without one', async () => {
    const store = useSocialStore()
    const send = vi.mocked(socialService.sendMessage)
    send.mockResolvedValueOnce(message({
      id: 'srv-2',
      type: 'VIDEO',
      content: '',
      image: '/api/v1/media/private/chat/chat_video/1/v.mp4?e=1&s=x',
      imageKey: 'chat/chat_video/1/v.mp4',
      mine: true,
      status: 'SENT',
    }))

    await store.resendMessage('c1', message({
      id: 'local-1',
      clientMsgId: 'c-1',
      type: 'VIDEO',
      content: '',
      image: 'blob:local-preview',
      imageKey: 'chat/chat_video/1/v.mp4',
      mine: true,
      status: 'FAILED',
      seq: 0,
    }))

    expect(send).toHaveBeenCalledWith('c1', '', expect.objectContaining({
      type: 'VIDEO',
      image: 'chat/chat_video/1/v.mp4',
      clientMsgId: 'c-1',
    }))

    await expect(store.resendMessage('c1', message({
      id: 'local-2',
      clientMsgId: 'c-2',
      type: 'IMAGE',
      content: '',
      image: 'blob:local-preview',
      mine: true,
      status: 'FAILED',
    }))).rejects.toThrow('媒体文件已失效')
  })

  it('removes neighbor and conversation when relation becomes blocked', () => {
    const store = useSocialStore()
    const friend: Friend = {
      id: 'u1',
      userId: 'u1',
      name: '邻居',
      avatar: 'avatar-person-1',
      verified: true,
      community: '阳光花园',
      letter: 'L',
    }
    const conversation: Conversation = {
      id: 'c1',
      type: 'FRIEND',
      peerId: 'u1',
      peerName: '邻居',
      peerAvatar: 'avatar-person-1',
      peerVerified: true,
      lastMessage: '你好',
      lastTime: '刚刚',
      unread: 0,
      canSend: true,
    }
    store.neighbors = [friend]
    store.conversations = [conversation]

    store.applyRelationChanged('u1', 'BLOCKED')

    expect(store.neighbors).toHaveLength(0)
    expect(store.conversations).toHaveLength(0)
  })
})
