import { computed } from 'vue'
import { useAppStore } from '../stores/app.store'

export function useTheme() {
  const app = useAppStore()
  const theme = computed(() => app.settings.theme)
  const isDark = computed(() => false)
  const elderMode = computed(() => app.settings.elderMode)

  function toggleElderMode(): void {
    app.toggleElderMode()
  }

  return { theme, isDark, elderMode, toggleElderMode }
}
