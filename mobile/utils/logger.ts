import { env } from '../config/env'
import { redactSensitive } from './desensitize'

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

const LEVEL_WEIGHT: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
}

const MIN_LEVEL: LogLevel = env.name === 'prod' || env.name === 'docker' ? 'warn' : 'debug'
let currentUserId = ''

function shouldLog(level: LogLevel): boolean {
  return LEVEL_WEIGHT[level] >= LEVEL_WEIGHT[MIN_LEVEL]
}

function write(level: LogLevel, tag: string, message: string, payload?: unknown): void {
  if (!shouldLog(level)) return
  const prefix = `[NeighInn/${level.toUpperCase()}][${tag}]`
  const safePayload = payload === undefined ? undefined : redactSensitive(payload)
  const userSuffix = currentUserId ? ` uid=${currentUserId}` : ''
  if (level === 'error') {
    console.error(`${prefix} ${message}${userSuffix}`, safePayload ?? '')
  } else if (level === 'warn') {
    console.warn(`${prefix} ${message}${userSuffix}`, safePayload ?? '')
  } else if (level === 'info') {
    console.info(`${prefix} ${message}${userSuffix}`, safePayload ?? '')
  } else {
    console.log(`${prefix} ${message}${userSuffix}`, safePayload ?? '')
  }
}

export const logger = {
  setUserId(id: string): void {
    currentUserId = id
  },
  debug(tag: string, message: string, payload?: unknown): void {
    write('debug', tag, message, payload)
  },
  info(tag: string, message: string, payload?: unknown): void {
    write('info', tag, message, payload)
  },
  warn(tag: string, message: string, payload?: unknown): void {
    write('warn', tag, message, payload)
  },
  error(tag: string, message: string, payload?: unknown): void {
    write('error', tag, message, payload)
  },
}

export function createTraceId(): string {
  return `ni-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}
