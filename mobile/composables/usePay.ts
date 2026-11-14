import { ref } from 'vue'
import { useOrderStore } from '../stores/order.store'
import { useToast } from './useToast'

export function usePay() {
  const orderStore = useOrderStore()
  const paying = ref(false)
  const { showToast } = useToast()

  async function payOrder(orderId: string, method: 'wechat' | 'alipay' = 'wechat'): Promise<boolean> {
    if (paying.value) return false
    paying.value = true
    try {
      await orderStore.pay(orderId, method)
      showToast('支付成功，货款已由平台托管')
      return true
    } catch (error) {
      showToast(error instanceof Error ? error.message : '支付失败，请重试', 'alert')
      return false
    } finally {
      paying.value = false
    }
  }

  return { paying, payOrder }
}
