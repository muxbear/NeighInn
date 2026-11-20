import { reactive } from 'vue'

export interface ConfirmOptions {
  title?: string
  message: string
  details?: string[]
  confirmText?: string
  cancelText?: string
  danger?: boolean
  /** 可选的勾选项（例如删除档案时同时注销移动端账号）。 */
  checkboxLabel?: string
  checkboxDefaultChecked?: boolean
}

export interface ConfirmResult {
  confirmed: boolean
  checked: boolean
}

interface ConfirmState {
  open: boolean
  title: string
  message: string
  details: string[]
  confirmText: string
  cancelText: string
  danger: boolean
  checkboxLabel: string
  checkboxChecked: boolean
}

const state = reactive<ConfirmState>({
  open: false,
  title: '操作确认',
  message: '',
  details: [],
  confirmText: '确认',
  cancelText: '取消',
  danger: false,
  checkboxLabel: '',
  checkboxChecked: false,
})

let resolver: ((value: ConfirmResult) => void) | null = null

function settle(confirmed: boolean): void {
  const resolve = resolver
  resolver = null
  state.open = false
  resolve?.({ confirmed, checked: state.checkboxChecked })
}

export function confirmWithCheckbox(options: ConfirmOptions | string): Promise<ConfirmResult> {
  settle(false)
  const opts = typeof options === 'string' ? { message: options } : options
  state.title = opts.title || '操作确认'
  state.message = opts.message
  state.details = opts.details || []
  state.confirmText = opts.confirmText || '确认'
  state.cancelText = opts.cancelText || '取消'
  state.danger = Boolean(opts.danger)
  state.checkboxLabel = opts.checkboxLabel || ''
  state.checkboxChecked = Boolean(opts.checkboxDefaultChecked)
  state.open = true
  return new Promise<ConfirmResult>((resolve) => {
    resolver = resolve
  })
}

export function confirmAction(options: ConfirmOptions | string): Promise<boolean> {
  return confirmWithCheckbox(options).then((result) => result.confirmed)
}

export function useConfirm() {
  return {
    confirm: confirmAction,
    confirmWithCheckbox,
    confirmState: state,
    resolveConfirm: settle,
  }
}
