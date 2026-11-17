import { reactive } from 'vue'

export interface ConfirmOptions {
  title?: string
  message: string
  details?: string[]
  confirmText?: string
  cancelText?: string
  danger?: boolean
}

interface ConfirmState {
  open: boolean
  title: string
  message: string
  details: string[]
  confirmText: string
  cancelText: string
  danger: boolean
}

const state = reactive<ConfirmState>({
  open: false,
  title: '操作确认',
  message: '',
  details: [],
  confirmText: '确认',
  cancelText: '取消',
  danger: false,
})

let resolver: ((value: boolean) => void) | null = null

function settle(value: boolean): void {
  const resolve = resolver
  resolver = null
  state.open = false
  resolve?.(value)
}

export function confirmAction(options: ConfirmOptions | string): Promise<boolean> {
  settle(false)
  const opts = typeof options === 'string' ? { message: options } : options
  state.title = opts.title || '操作确认'
  state.message = opts.message
  state.details = opts.details || []
  state.confirmText = opts.confirmText || '确认'
  state.cancelText = opts.cancelText || '取消'
  state.danger = Boolean(opts.danger)
  state.open = true
  return new Promise<boolean>((resolve) => {
    resolver = resolve
  })
}

export function useConfirm() {
  return { confirm: confirmAction, confirmState: state, resolveConfirm: settle }
}
