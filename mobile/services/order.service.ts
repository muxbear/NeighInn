import * as orderApi from '../api/order.api'
import type {
  CreateOrderPayload,
  CreateOrderResult,
  DisputePayload,
  Order,
  OrderQuery,
  PageResult,
  ReviewPayload,
} from '../models'

export const orderService = {
  create(payload: CreateOrderPayload): Promise<CreateOrderResult> {
    return orderApi.createOrder(payload)
  },

  getOrders(query: OrderQuery = {}): Promise<PageResult<Order>> {
    return orderApi.getOrders(query)
  },

  getDetail(id: string): Promise<Order> {
    return orderApi.getOrderDetail(id)
  },

  setAppointment(id: string, payload: { time: string; place: string; note?: string }): Promise<Order> {
    return orderApi.setAppointment(id, payload)
  },

  confirmApplication(id: string): Promise<Order> {
    return orderApi.confirmApplication(id)
  },

  confirmInspection(id: string): Promise<Order> {
    return orderApi.confirmInspection(id)
  },

  cancel(id: string): Promise<Order> {
    return orderApi.cancelOrder(id)
  },

  dispute(id: string, payload: DisputePayload): Promise<{ success: boolean; order: Order }> {
    return orderApi.submitDispute(id, payload)
  },

  review(id: string, payload: ReviewPayload): Promise<{ success: boolean; rating: number }> {
    return orderApi.submitReview(id, payload)
  },
}
