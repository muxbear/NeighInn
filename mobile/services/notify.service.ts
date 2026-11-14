/**
 * 推送统一入口：订阅消息 / APNs / 厂商通道 / HarmonyOS Push。
 * 当前没有接入原生推送插件，先做能力占位与站内提醒。
 */
export const notifyService = {
  async requestPermission(): Promise<boolean> {
    // #ifdef MP-WEIXIN
    return true
    // #endif
    // #ifndef MP-WEIXIN
    return true
    // #endif
  },

  showInApp(message: string): void {
    if (typeof uni === 'undefined') return
    uni.showToast({ title: message, icon: 'none', duration: 1800 })
  },

  /** 推送 Token 注册；接入极光/UniPush/APNs 后替换实现 */
  async registerPushToken(): Promise<string> {
    return ''
  },
}
