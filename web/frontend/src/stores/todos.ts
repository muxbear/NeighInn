import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { dashboardApi } from '@/api'

type TodoItem = {
  key: string
  title: string
  description: string
  count: number
  route: string
  permission: string
  icon: string
  color: string
  oldestPendingAt: number
  latestCertId: string
  communityId?: number | null
  breakdown: Record<string, number>
}

export const useTodoStore = defineStore('todos', () => {
  const items = ref<TodoItem[]>([])
  const loading = ref(false)
  const lastLoadedAt = ref(0)
  let timer: number | undefined
  // 请求序号用于丢弃快速切换社区时较早返回的响应，避免旧社区数据覆盖新社区。
  let requestSeq = 0
  // 待办必须与顶部「当前运营空间」一致；未显式传参时沿用上一次社区。
  let currentCommunityId: number | undefined

  const total = computed(() => items.value.reduce((sum, item) => sum + item.count, 0))
  const certTodo = computed(() => items.value.find((item) => item.key === 'certification'))

  async function refresh(communityId?: number): Promise<void> {
    if (communityId !== undefined) currentCommunityId = communityId
    const seq = ++requestSeq
    loading.value = true
    try {
      const data = (await dashboardApi.todos(currentCommunityId)) as TodoItem[]
      if (seq !== requestSeq) return
      items.value = data
      lastLoadedAt.value = Date.now()
    } catch {
      // 保留上一次成功数据，后台操作不被待办刷新失败打断。
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  function onFocus(): void {
    refresh()
  }

  function onVisibilityChange(): void {
    if (document.visibilityState === 'visible') refresh()
  }

  function startPolling(communityId?: number, intervalMs = 60_000): void {
    stopPolling()
    if (communityId !== undefined) currentCommunityId = communityId
    refresh(currentCommunityId)
    timer = window.setInterval(() => refresh(currentCommunityId), intervalMs)
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibilityChange)
  }

  function stopPolling(): void {
    if (timer) window.clearInterval(timer)
    timer = undefined
    window.removeEventListener('focus', onFocus)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }

  return {
    items,
    loading,
    lastLoadedAt,
    total,
    certTodo,
    refresh,
    startPolling,
    stopPolling,
  }
})
