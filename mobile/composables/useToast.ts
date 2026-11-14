import { reactive } from 'vue'

const state = reactive({
  visible: false,
  text: '',
  icon: 'check',
})

let timer: any = null

export function useToast() {
  function show(text: string, icon = 'check', duration = 1800): void {
    state.text = text
    state.icon = icon
    state.visible = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      state.visible = false
      timer = null
    }, duration)
  }

  function hide(): void {
    state.visible = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  return { toast: state, showToast: show, hideToast: hide }
}
