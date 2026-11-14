/** UUID v4 幂等键生成；App/小程序运行时可能无 crypto，提供降级实现 */

let counter = 0

export function uuidv4(): string {
  const cryptoRef = (globalThis as any).crypto
  if (cryptoRef && typeof cryptoRef.randomUUID === 'function') {
    return cryptoRef.randomUUID()
  }

  const template = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
  return template.replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0
    const value = char === 'x' ? random : (random & 0x3) | 0x8
    return value.toString(16)
  })
}

export function createIdempotencyKey(scope = 'ni'): string {
  counter = (counter + 1) % 10000
  return `${scope}-${Date.now()}-${counter}-${uuidv4()}`
}

/** 同一个业务动作（如一次支付）复用同一个 key */
export class IdempotencyScope {
  private key: string

  constructor(scope: string) {
    this.key = createIdempotencyKey(scope)
  }

  get value(): string {
    return this.key
  }

  reset(scope = 'ni'): string {
    this.key = createIdempotencyKey(scope)
    return this.key
  }
}
