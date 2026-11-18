import { env } from '../config/env'
import { logger } from '../utils/logger'
import { secureStorage } from '../utils/storage'

export type WsAction =
  | 'MSG_SEND'
  | 'MSG_ACK'
  | 'MSG_READ'
  | 'PING'
  | 'MSG_PUSH'
  | 'ORDER_EVENT'
  | 'AUDIT_EVENT'
  | 'NOTIFY'
  | 'PONG'

export type WsHandler = (action: WsAction | string, payload: any) => void

const HEARTBEAT_INTERVAL = 30 * 1000
const MAX_RECONNECT_DELAY = 60 * 1000

/**
 * Docker / H5 同源部署时 env.wsUrl 为相对路径（/api/v1/ws），浏览器 WebSocket
 * 需要绝对地址；按当前页面的协议与域名补全为 ws:// 或 wss://。
 * App / 小程序端使用绝对 ws:// / wss:// 地址时原样返回。
 */
function resolveWsUrl(raw: string): string {
  if (!raw.startsWith('/')) return raw
  const loc = (globalThis as any).location
  if (!loc || !loc.host) return raw
  const protocol = loc.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${loc.host}${raw}`
}

class WsService {
  private task: any = null
  private handlers = new Set<WsHandler>()
  private heartbeatTimer: any = null
  private reconnectTimer: any = null
  private reconnectAttempt = 0
  private paused = false
  private connected = false
  private waitingPong = 0

  onMessage(handler: WsHandler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  connect(): void {
    if (this.connected) return
    if (env.mock) {
      this.connected = true
      logger.info('WS', 'mock connected')
      return
    }
    if (this.paused || this.task) return
    if (typeof uni === 'undefined') return

    const token = secureStorage.getAccessToken()
    if (!token) return

    try {
      const task = uni.connectSocket({
        url: `${resolveWsUrl(env.wsUrl)}?token=${encodeURIComponent(token)}`,
        complete: () => undefined,
      })
      this.task = task

      task.onOpen(() => {
        this.connected = true
        this.reconnectAttempt = 0
        this.waitingPong = 0
        logger.info('WS', 'connected')
        this.startHeartbeat()
      })

      task.onMessage((event: any) => {
        this.handleIncoming(event?.data)
      })

      task.onClose(() => {
        this.connected = false
        this.task = null
        this.stopHeartbeat()
        logger.warn('WS', 'closed')
        this.scheduleReconnect()
      })

      task.onError((error: any) => {
        this.connected = false
        this.task = null
        this.stopHeartbeat()
        logger.warn('WS', 'error', error)
        this.scheduleReconnect()
      })
    } catch (error) {
      logger.warn('WS', 'connect failed', error)
      this.scheduleReconnect()
    }
  }

  disconnect(): void {
    this.paused = true
    this.stopHeartbeat()
    clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    if (this.task) {
      try {
        this.task.close({ code: 1000, reason: 'client close' })
      } catch {
        // ignore
      }
    }
    this.task = null
    this.connected = false
  }

  pause(): void {
    this.paused = true
    this.stopHeartbeat()
  }

  resume(): void {
    if (!this.paused) return
    this.paused = false
    if (!this.connected) this.connect()
  }

  send(action: WsAction, payload: Record<string, any> = {}): void {
    const frame = { action, payload }
    if (env.mock) {
      if (action === 'MSG_SEND') {
        setTimeout(() => {
          this.dispatch('MSG_ACK', { clientMsgId: payload.clientMsgId })
        }, 120)
      }
      if (action === 'PING') {
        setTimeout(() => this.dispatch('PONG', { ts: Date.now() }), 60)
      }
      return
    }
    if (!this.task || !this.connected) return
    try {
      this.task.send({ data: JSON.stringify(frame) })
    } catch (error) {
      logger.warn('WS', 'send failed', error)
    }
  }

  sendMessage(conversationId: string, content: string, clientMsgId: string): void {
    this.send('MSG_SEND', { clientMsgId, conversationId, type: 'TEXT', content })
  }

  markRead(conversationId: string, lastMsgSeq: number): void {
    this.send('MSG_READ', { conversationId, lastMsgSeq })
  }

  private handleIncoming(raw: unknown): void {
    if (typeof raw !== 'string') return
    try {
      const frame = JSON.parse(raw)
      if (frame && typeof frame.action === 'string') {
        if (frame.action === 'PONG') this.waitingPong = 0
        this.dispatch(frame.action, frame.payload ?? {})
      }
    } catch (error) {
      logger.warn('WS', 'invalid frame', error)
    }
  }

  private dispatch(action: string, payload: any): void {
    this.handlers.forEach((handler) => {
      try {
        handler(action, payload)
      } catch (error) {
        logger.error('WS', `handler error for ${action}`, error)
      }
    })
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.waitingPong >= 2) {
        logger.warn('WS', 'heartbeat timeout')
        this.connected = false
        this.task = null
        this.stopHeartbeat()
        this.scheduleReconnect()
        return
      }
      this.waitingPong += 1
      this.send('PING', { ts: Date.now() })
    }, HEARTBEAT_INTERVAL)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect(): void {
    if (this.paused || env.mock) return
    clearTimeout(this.reconnectTimer)
    const delay = Math.min(MAX_RECONNECT_DELAY, 1000 * Math.pow(2, this.reconnectAttempt))
    this.reconnectAttempt += 1
    logger.info('WS', `reconnect in ${delay}ms`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}

export const wsService = new WsService()
