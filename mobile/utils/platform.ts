/** 平台判断统一收敛在这里，页面不写条件编译 */

export function isAndroid(): boolean {
  let result = false
  // #ifdef APP-ANDROID
  result = true
  // #endif
  return result
}

export function isIOS(): boolean {
  let result = false
  // #ifdef APP-IOS
  result = true
  // #endif
  return result
}

export function isHarmony(): boolean {
  let result = false
  // #ifdef APP-HARMONY
  result = true
  // #endif
  return result
}

export function isApp(): boolean {
  return isAndroid() || isIOS() || isHarmony()
}

export function isMpWeixin(): boolean {
  let result = false
  // #ifdef MP-WEIXIN
  result = true
  // #endif
  return result
}

export function isMpAlipay(): boolean {
  let result = false
  // #ifdef MP-ALIPAY
  result = true
  // #endif
  return result
}

export function isWeb(): boolean {
  let result = false
  // #ifdef WEB
  result = true
  // #endif
  return result
}

export function platformName(): string {
  if (isMpWeixin()) return '微信小程序'
  if (isMpAlipay()) return '支付宝小程序'
  if (isAndroid()) return 'Android'
  if (isIOS()) return 'iOS'
  if (isHarmony()) return 'HarmonyOS'
  if (isWeb()) return 'Web'
  return '未知平台'
}

/** 一键登录依赖运营商 UTS 插件，目前仅 App 端可用 */
export function supportsOneClickLogin(): boolean {
  return isApp()
}

export function supportsWechatLogin(): boolean {
  return isMpWeixin() || isApp()
}
