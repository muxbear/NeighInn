/** 脱敏工具：手机号、姓名、身份证号；日志与界面共用 */

export function maskPhone(phone: string): string {
  const value = String(phone || '').replace(/\s/g, '')
  if (value.length < 7) return value
  return `${value.slice(0, 3)} **** ${value.slice(-4)}`
}

export function maskName(name: string): string {
  const value = String(name || '')
  if (!value) return ''
  if (value.length === 1) return value
  return `${value.slice(0, 1)}${'*'.repeat(Math.min(2, value.length - 1))}`
}

export function maskIdCard(idCard: string): string {
  const value = String(idCard || '')
  if (value.length < 8) return value
  return `${value.slice(0, 6)}********${value.slice(-4)}`
}

export function maskAddress(address: string): string {
  const value = String(address || '')
  if (value.length <= 6) return value
  return `${value.slice(0, 6)}****`
}

/** 日志脱敏：递归替换敏感字段 */
export function redactSensitive(value: unknown, depth = 0): unknown {
  if (depth > 4 || value === null || value === undefined) return value
  if (Array.isArray(value)) return value.map((item) => redactSensitive(item, depth + 1))
  if (typeof value !== 'object') return value

  const record = value as Record<string, unknown>
  const result: Record<string, unknown> = {}
  for (const key of Object.keys(record)) {
    const lower = key.toLowerCase()
    if (
      lower.includes('token') ||
      lower.includes('password') ||
      lower.includes('secret') ||
      lower.includes('idcard') ||
      lower === 'phone'
    ) {
      result[key] = '***'
    } else if (lower === 'name' || lower === 'realname') {
      result[key] = maskName(String(record[key] ?? ''))
    } else {
      result[key] = redactSensitive(record[key], depth + 1)
    }
  }
  return result
}
