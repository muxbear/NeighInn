import { APP_INFO } from '../config/env'

/** 打开用户协议 / 隐私政策说明（正式内容由运营配置的 H5 页面承载）。 */
export function openAgreement(type: 'user' | 'privacy'): void {
  const title = type === 'user' ? '用户协议' : '隐私政策'
  const url = type === 'user' ? APP_INFO.agreementUrl : APP_INFO.privacyUrl
  uni.showModal({
    title,
    content: `${title}正式内容请访问：${url}`,
    showCancel: false,
    confirmText: '我知道了',
  })
}
