import type { Item, SellerSummary, TradeType } from './item.model'

export type OrderStatus =
  | 'PENDING_PAYMENT'
  | 'ESCROWED'
  | 'APPLIED'
  | 'PENDING_CONFIRM'
  | 'CONFIRMED'
  | 'APPOINTMENT'
  | 'INSPECTING'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'REFUNDED'
  | 'DISPUTING'

export type OrderRole = 'buyer' | 'seller'

export interface OrderTimelineItem {
  key: string
  title: string
  time?: string
  done: boolean
  active?: boolean
}

export interface Appointment {
  time: string
  place: string
  note?: string
  status: 'PENDING' | 'CONFIRMED' | 'CANCELLED' | 'EXPIRED'
}

export interface Order {
  id: string
  orderNo: string
  tradeType: TradeType
  tradeTypeCode: 'MONETARY' | 'FREE_GIFT' | 'BARTER'
  status: OrderStatus
  statusText: string
  item: Item
  offeredItems?: Item[]
  amount: number
  buyer: SellerSummary
  seller: SellerSummary
  role: OrderRole
  createdAt: number
  createdAtText: string
  appointment?: Appointment
  timeline: OrderTimelineItem[]
  canPay?: boolean
  canConfirmApplication?: boolean
  canCompleteTrade?: boolean
  canAppointment?: boolean
  canInspect?: boolean
  canReview?: boolean
  canCancel?: boolean
  canDispute?: boolean
  reviewable?: boolean
  progressText?: string
}

export interface OrderQuery {
  type?: 'free' | 'swap' | 'monetary'
  page?: number
  pageSize?: number
}

export interface CreateOrderPayload {
  itemId: string
  tradeType: TradeType
  offeredItemIds?: string[]
  note?: string
}

export interface CreateOrderResult {
  orderId: string
  orderNo: string
  amount: number
  expireAt: number
}

export interface ReviewPayload {
  rating: number
  tags: string[]
  content: string
  anonymous: boolean
}

export interface DisputePayload {
  reason: string
  description: string
  images: string[]
}

export interface WalletSummary {
  balance: number
  escrow: number
  withdrawable: number
}

export interface WalletTransaction {
  id: string
  title: string
  amount: number
  direction: 'in' | 'out'
  time: string
  icon: string
}
