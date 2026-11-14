import type {
  PageResult,
  PaymentPrepayResult,
  PaymentStatusResult,
  WalletSummary,
  WalletTransaction,
} from '../models'
import { get, post } from './request'
import { withQuery } from './query'

export function prepay(orderId: string, method: 'wechat' | 'alipay' = 'wechat'): Promise<PaymentPrepayResult> {
  return post<PaymentPrepayResult>('/payments/prepay', { orderId, method }, { loading: true })
}

export function getPaymentStatus(orderNo: string): Promise<PaymentStatusResult> {
  return get<PaymentStatusResult>(`/payments/${orderNo}/status`, undefined, { retry: false })
}

export function getWallet(): Promise<WalletSummary> {
  return get<WalletSummary>('/wallet')
}

export function getWalletTransactions(page = 1, pageSize = 20): Promise<PageResult<WalletTransaction>> {
  return get<PageResult<WalletTransaction>>(withQuery('/wallet/transactions', { page, pageSize }))
}

export function requestWithdraw(amount: number): Promise<{ success: boolean; status: string }> {
  return post('/wallet/withdrawals', { amount }, { loading: true })
}
