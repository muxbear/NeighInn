import { useSocialStore } from '../stores/social.store'
import { wsService } from '../services/ws.service'

export function useIM() {
  const social = useSocialStore()

  async function openChat(peerId: string, itemId?: string): Promise<void> {
    const conversation = await social.openConversation(peerId, itemId)
    uni.navigateTo({ url: `/pages/social/chat?id=${conversation.id}` })
  }

  function openConversation(conversationId: string, itemId?: string): void {
    uni.navigateTo({ url: `/pages/social/chat?id=${conversationId}${itemId ? `&itemId=${itemId}` : ''}` })
  }

  function markRead(conversationId: string, lastSeq = 0): void {
    social.markConversationRead(conversationId)
    wsService.markRead(conversationId, lastSeq)
  }

  return {
    social,
    openChat,
    openConversation,
    markRead,
  }
}
