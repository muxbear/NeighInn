import { computed } from 'vue'
import { useAppStore } from '../stores/app.store'

export function useElderMode() {
  const app = useAppStore()
  const enabled = computed(() => app.settings.elderMode)
  const fontExtra = computed(() => (enabled.value ? 2 : 0))
  const buttonExtra = computed(() => (enabled.value ? 8 : 0))

  function toggle(): void {
    app.toggleElderMode()
  }

  return { enabled, fontExtra, buttonExtra, toggle }
}
