import type {
  CreateOrderPayload,
  CreateOrderResult,
  DisputePayload,
  Order,
  OrderQuery,
  PageResult,
  ReviewPayload,
} from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export function createOrder(payload: CreateOrderPayload): Promise<CreateOrderResult> {
  return post<CreateOrderResult>('/orders', payload as unknown as Record<string, any>, { loading: true })
}

export function getOrders(query: OrderQuery = {}): Promise<PageResult<Order>> {
  return get<PageResult<Order>>(withQuery('/orders', query))
}

export function getOrderDetail(id: string): Promise<Order> {
  return get<Order>(`/orders/${id}`)
}

export function setAppointment(
  id: string,
  payload: { time: string; place: string; note?: string },
): Promise<Order> {
  return post<Order>(`/orders/${id}/appointment`, payload, { loading: true })
}

export function confirmApplication(id: string): Promise<Order> {
  return post<Order>(`/orders/${id}/confirm-application`, {}, { loading: true })
}

export function confirmInspection(id: string): Promise<Order> {
  return post<Order>(`/orders/${id}/confirm`, {}, { loading: true })
}

export function cancelOrder(id: string): Promise<Order> {
  return post<Order>(`/orders/${id}/cancel`, {}, { loading: true })
}

export function submitDispute(id: string, payload: DisputePayload): Promise<{ success: boolean; order: Order }> {
  return post(`/orders/${id}/dispute`, payload as unknown as Record<string, any>, { loading: true })
}

export function submitReview(id: string, payload: ReviewPayload): Promise<{ success: boolean; rating: number }> {
  return post(`/orders/${id}/reviews`, payload as unknown as Record<string, any>, { loading: true })
}
