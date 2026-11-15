/** 纯展示格式化工具：金额、距离、耗时、时间、数量 */

function pad2(value: number): string {
  return value < 10 ? `0${value}` : `${value}`
}

/** ¥128 / ¥128.00，整数金额不补小数 */
export function formatPrice(price: number | string, withSymbol = true): string {
  const num = typeof price === 'number' ? price : Number.parseFloat(String(price))
  const safe = Number.isFinite(num) ? num : 0
  const text = Number.isInteger(safe) ? `${safe}` : safe.toFixed(2)
  return withSymbol ? `¥${text}` : text
}

/** 金额数字（不带符号），用于输入框/统计 */
export function formatAmount(price: number | string, decimals = 2): string {
  const num = typeof price === 'number' ? price : Number.parseFloat(String(price))
  const safe = Number.isFinite(num) ? num : 0
  return safe.toFixed(decimals)
}

/** 小区行政区划展示：优先 regionPath，其次按省/市/区/街道拼接 */
export function formatCommunityRegion(community: {
  regionPath?: string
  province?: string
  city?: string
  district?: string
  street?: string
} | null | undefined): string {
  if (!community) return ''
  if (community.regionPath) return community.regionPath
  return [community.province, community.city, community.district, community.street]
    .filter((name) => Boolean(name))
    .join(' ')
}

/** 米 → 10m 级距离文案；10m 内显示“约 8m”，1km 以上保留 1 位小数 */
export function formatDistance(meters: number): string {
  if (!Number.isFinite(meters) || meters < 0) return '距离未知'
  if (meters < 10) return `约 ${Math.max(1, Math.round(meters))}m`
  if (meters < 1000) return `约 ${Math.round(meters / 10) * 10}m`
  return `约 ${(meters / 1000).toFixed(1)}km`
}

/** 步行/骑行/驾车耗时（按常见速度估算，结果由服务端优先返回） */
export function formatTravelTime(meters: number, mode: 'walk' | 'bike' | 'car'): string {
  const speedMetersPerMinute = mode === 'walk' ? 72 : mode === 'bike' ? 250 : 720
  const minutes = Math.max(1, Math.round(Math.max(0, meters) / speedMetersPerMinute))
  return `${minutes}分钟`
}

/** 相对时间：刚刚 / 18分钟前 / 3小时前 / 昨天 / MM-DD / YYYY-MM-DD */
export function formatRelativeTime(timestamp: number, now = Date.now()): string {
  if (!timestamp) return ''
  const diff = Math.max(0, now - timestamp)
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour

  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)}分钟前`
  if (diff < day) return `${Math.floor(diff / hour)}小时前`
  if (diff < 2 * day) return '昨天'

  const date = new Date(timestamp)
  const nowDate = new Date(now)
  if (date.getFullYear() === nowDate.getFullYear()) {
    return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
  }
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

export function formatDateTime(timestamp: number): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

export function formatDate(timestamp: number): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

export function formatTime(timestamp: number): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

export function formatThousands(count: number): string {
  if (!Number.isFinite(count)) return '0'
  return `${Math.round(count)}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** 数量：9999 以下原值，以上用“1.2万” */
export function formatCount(count: number): string {
  if (!Number.isFinite(count)) return '0'
  if (count < 10000) return `${count}`
  return `${(count / 10000).toFixed(1).replace(/\.0$/, '')}万`
}

/** 倒计时 / 视频时长：mm:ss */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${pad2(minutes)}:${pad2(seconds)}`
}

export function formatVideoDuration(seconds: number): string {
  return formatCountdown(seconds * 1000)
}

export function formatDays(days: number): string {
  if (days < 30) return `${days}天`
  if (days < 365) return `${Math.floor(days / 30)}个月`
  return `${(days / 365).toFixed(1).replace(/\.0$/, '')}年`
}

export function formatCredit(score: number): string {
  if (score >= 90) return '信用极好'
  if (score >= 75) return '信用良好'
  if (score >= 60) return '信用一般'
  return '信用待提升'
}
