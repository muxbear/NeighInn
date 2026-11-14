export function withQuery(path: string, params: Record<string, any> = {}): string {
  const pairs: string[] = []
  for (const key of Object.keys(params)) {
    const value = params[key]
    if (value === undefined || value === null || value === '') continue
    pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  }
  return pairs.length ? `${path}?${pairs.join('&')}` : path
}
