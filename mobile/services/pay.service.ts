import * as payApi from '../api/pay.api'
import { ApiError } from '../api/errors'
import type {
  PageResult,
  PaymentPrepayResult,
  PaymentStatusResult,
  WalletSummary,
  WalletTransaction,
} from '../models'

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export const payService = {
  prepay(orderId: string, method: 'wechat' | 'alipay' = 'wechat'): Promise<PaymentPrepayResult> {
    return payApi.prepay(orderId, method)
  },

  /**
   * 支付结果双通道确认：端侧查询 + 服务端异步通知。
   * 这里做轮询兜底，最多 5 次，每次间隔 1s；不做乐观更新。
   */
  async waitPaymentSuccess(orderNo: string, attempts = 5): Promise<PaymentStatusResult> {
    for (let index = 0; index < attempts; index += 1) {
      const result = await payApi.getPaymentStatus(orderNo)
      if (result.status === 'SUCCESS') return result
      if (result.status === 'FAILED') throw new ApiError(40001, '支付失败，请重试')
      await sleep(1000)
    }
    throw new ApiError(50000, '支付结果确认中，请稍后在订单中查看')
  },

  getWallet(): Promise<WalletSummary> {
    return payApi.getWallet()
  },

  getTransactions(page = 1, pageSize = 20): Promise<PageResult<WalletTransaction>> {
    return payApi.getWalletTransactions(page, pageSize)
  },

  async withdraw(amount: number): Promise<{ success: boolean; status: string }> {
    if (!Number.isFinite(amount) || amount <= 0) throw new ApiError(40001, '请输入有效提现金额')
    return payApi.requestWithdraw(amount)
  },
}
