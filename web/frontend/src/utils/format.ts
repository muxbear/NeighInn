export function formatDateTime(value: unknown, fallback = '今天 09:32'): string {
  if (!value) return fallback
  if (typeof value === 'string' && !value.includes('T')) return value
  const date = new Date(String(value))
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
