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
  breakdown: Record<string, number>
}

export const useTodoStore = defineStore('todos', () => {
  const items = ref<TodoItem[]>([])
  const loading = ref(false)
  const lastLoadedAt = ref(0)
  let timer: number | undefined
  let inFlight = false

  const total = computed(() => items.value.reduce((sum, item) => sum + item.count, 0))
  const certTodo = computed(() => items.value.find((item) => item.key === 'certification'))

  async function refresh(): Promise<void> {
    if (inFlight) return
    inFlight = true
    loading.value = true
    try {
      items.value = (await dashboardApi.todos()) as TodoItem[]
      lastLoadedAt.value = Date.now()
    } catch {
      // 保留上一次成功数据，后台操作不被待办刷新失败打断。
    } finally {
      inFlight = false
      loading.value = false
    }
  }

  function onFocus(): void {
    refresh()
  }

  function onVisibilityChange(): void {
    if (document.visibilityState === 'visible') refresh()
  }

  function startPolling(intervalMs = 60_000): void {
    stopPolling()
    refresh()
    timer = window.setInterval(refresh, intervalMs)
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
