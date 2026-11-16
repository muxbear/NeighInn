import { defineStore } from 'pinia'
import { ref } from 'vue'
import { operationsApi } from '@/api'

/**
 * 侧边栏动态徽标：物品待审核数必须与「社区物品」页指标卡同源（当前运营小区），
 * 因此复用 /operations/overview，而不是全局待办数量。
 */
export const useNavBadgeStore = defineStore('navBadges', () => {
  const itemPending = ref(0)

  function setItemPending(value: number): void {
    itemPending.value = Math.max(0, Number(value || 0))
  }

  async function refresh(communityId?: number): Promise<void> {
    try {
      const data = await operationsApi.overview('items', { communityId })
      setItemPending(Number(data?.metrics?.pendingReview || 0))
    } catch {
      // 保留上一次成功数据，侧边栏不因网络抖动闪回 0
    }
  }

  return { itemPending, setItemPending, refresh }
})
