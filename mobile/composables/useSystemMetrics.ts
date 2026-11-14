import { computed } from 'vue'
import { useAppStore } from '../stores/app.store'

export function useSystemMetrics() {
  const app = useAppStore()
  if (!app.statusBarHeight) app.measureWindow()

  const statusBarHeight = computed(() => app.statusBarHeight || 20)
  const safeAreaBottom = computed(() => app.safeAreaBottom)

  return { statusBarHeight, safeAreaBottom }
}
