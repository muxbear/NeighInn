import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  CreateOrderPayload,
  DisputePayload,
  Order,
  ReviewPayload,
} from '../models'
import { orderService } from '../services/order.service'
import { payService } from '../services/pay.service'

type OrderType = 'free' | 'swap' | 'monetary'

export const useOrderStore = defineStore('order', () => {
  const ordersByType = ref<Record<OrderType, Order[]>>({
    free: [],
    swap: [],
    monetary: [],
  })
  const loading = ref(false)
  const currentOrder = ref<Order | null>(null)
  const payingOrderId = ref('')

  async function fetchOrders(type: OrderType, refresh = false): Promise<void> {
    loading.value = true
    try {
      const result = await orderService.getOrders({ type, page: 1, pageSize: 50 })
      ordersByType.value = { ...ordersByType.value, [type]: result.list }
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(id: string): Promise<Order> {
    const order = await orderService.getDetail(id)
    currentOrder.value = order
    return order
  }

  async function create(payload: CreateOrderPayload): Promise<string> {
    const result = await orderService.create(payload)
    await fetchOrders(payload.tradeType === '免费' ? 'free' : payload.tradeType === '互换' ? 'swap' : 'monetary', true)
    return result.orderId
  }

  async function pay(orderId: string, method: 'wechat' | 'alipay' = 'wechat'): Promise<Order> {
    payingOrderId.value = orderId
    try {
      const prepay = await payService.prepay(orderId, method)
      await payService.waitPaymentSuccess(prepay.orderNo)
      return await fetchDetail(orderId)
    } finally {
      payingOrderId.value = ''
    }
  }

  async function setAppointment(
    orderId: string,
    payload: { time: string; place: string; note?: string },
  ): Promise<Order> {
    const order = await orderService.setAppointment(orderId, payload)
    currentOrder.value = order
    return order
  }

  async function confirmApplication(orderId: string): Promise<Order> {
    const order = await orderService.confirmApplication(orderId)
    currentOrder.value = order
    return order
  }

  async function confirmInspection(orderId: string): Promise<Order> {
    const order = await orderService.confirmInspection(orderId)
    currentOrder.value = order
    return order
  }

  async function cancel(orderId: string): Promise<Order> {
    const order = await orderService.cancel(orderId)
    currentOrder.value = order
    return order
  }

  async function dispute(orderId: string, payload: DisputePayload): Promise<void> {
    await orderService.dispute(orderId, payload)
    await fetchDetail(orderId)
  }

  async function review(orderId: string, payload: ReviewPayload): Promise<void> {
    await orderService.review(orderId, payload)
    await fetchDetail(orderId)
  }

  return {
    ordersByType,
    loading,
    currentOrder,
    payingOrderId,
    fetchOrders,
    fetchDetail,
    create,
    pay,
    setAppointment,
    confirmApplication,
    confirmInspection,
    cancel,
    dispute,
    review,
  }
})
