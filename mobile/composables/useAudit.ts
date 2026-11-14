import { onUnmounted, ref } from 'vue'
import type { AuditProgress } from '../models'
import { auditService } from '../services/audit.service'

export function useAudit() {
  const progress = ref<AuditProgress | null>(null)
  const polling = ref(false)
  const error = ref('')
  let timer: any = null
  let stopped = false

  async function pollOnce(itemId: string): Promise<AuditProgress> {
    const result = await auditService.getProgress(itemId)
    progress.value = result
    return result
  }

  function start(
    itemId: string,
    onDone?: (result: AuditProgress) => void,
    options: { interval?: number; maxAttempts?: number } = {},
  ): void {
    stop()
    stopped = false
    polling.value = true
    error.value = ''
    const interval = options.interval ?? 1400
    const maxAttempts = options.maxAttempts ?? 20
    let attempts = 0

    const tick = async () => {
      if (stopped) return
      attempts += 1
      try {
        const result = await pollOnce(itemId)
        if (result.status === 'PASSED' || result.status === 'REJECTED' || result.status === 'TIMEOUT') {
          polling.value = false
          onDone?.(result)
          return
        }
        if (attempts >= maxAttempts) {
          polling.value = false
          onDone?.(result)
          return
        }
        timer = setTimeout(tick, interval)
      } catch (err) {
        error.value = err instanceof Error ? err.message : '质检进度获取失败'
        if (attempts < maxAttempts) {
          timer = setTimeout(tick, interval * 2)
        } else {
          polling.value = false
        }
      }
    }

    tick()
  }

  function stop(): void {
    stopped = true
    polling.value = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  onUnmounted(stop)

  return { progress, polling, error, start, stop, pollOnce }
}
