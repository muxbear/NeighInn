/**
 * 环境配置。
 * 默认 'local' 联调统一服务端；离线演示用 'dev'（Mock）；H5 Docker 部署用 'docker'。
 */
export interface EnvConfig {
  name: 'dev' | 'local' | 'docker' | 'test' | 'staging' | 'prod'
  baseUrl: string
  wsUrl: string
  uploadUrl: string
  mock: boolean
  mockLatency: number
  requestTimeout: number
}

/**
 * 本地联调主机（local 环境使用）。
 * - H5 / 微信开发者工具：保持 127.0.0.1；
 * - Android 模拟器：改为 10.0.2.2；
 * - 真机：改为电脑局域网 IP（如 192.168.1.100），并把 web/backend/.env 的 APP_HOST 改为 0.0.0.0。
 */
const LOCAL_HOST = '127.0.0.1'
const LOCAL_API_URL = `http://${LOCAL_HOST}:5193/api/v1`

const ENVS: Record<EnvConfig['name'], EnvConfig> = {
  dev: {
    name: 'dev',
    baseUrl: 'https://api-dev.neighinn.example.com/v1',
    wsUrl: 'wss://api-dev.neighinn.example.com/ws',
    uploadUrl: 'https://upload-dev.neighinn.example.com',
    mock: true,
    mockLatency: 220,
    requestTimeout: 15000,
  },
  local: {
    name: 'local',
    baseUrl: LOCAL_API_URL,
    wsUrl: `ws://${LOCAL_HOST}:5193/api/v1/ws`,
    uploadUrl: LOCAL_API_URL,
    mock: false,
    mockLatency: 0,
    requestTimeout: 15000,
  },
  /**
   * Docker / nginx 同源部署专用（仅 H5 使用）。
   * nginx 把 /api/ 反代到统一服务端；WebSocket 地址在 ws.service 中按当前页面
   * 的协议与域名补全为 ws:// 或 wss://。
   */
  docker: {
    name: 'docker',
    baseUrl: '/api/v1',
    wsUrl: '/api/v1/ws',
    uploadUrl: '/api/v1',
    mock: false,
    mockLatency: 0,
    requestTimeout: 15000,
  },
  test: {
    name: 'test',
    baseUrl: 'https://api-test.neighinn.example.com/v1',
    wsUrl: 'wss://api-test.neighinn.example.com/ws',
    uploadUrl: 'https://upload-test.neighinn.example.com',
    mock: true,
    mockLatency: 120,
    requestTimeout: 15000,
  },
  staging: {
    name: 'staging',
    baseUrl: 'https://api-staging.neighinn.example.com/v1',
    wsUrl: 'wss://api-staging.neighinn.example.com/ws',
    uploadUrl: 'https://upload-staging.neighinn.example.com',
    mock: false,
    mockLatency: 0,
    requestTimeout: 15000,
  },
  prod: {
    name: 'prod',
    baseUrl: 'https://api.neighinn.com/v1',
    wsUrl: 'wss://api.neighinn.com/ws',
    uploadUrl: 'https://upload.neighinn.com',
    mock: false,
    mockLatency: 0,
    requestTimeout: 15000,
  },
}

/** 切换环境：改这里即可；HBuilderX 发版前务必确认为 staging / prod。
 * dev = 本地 Mock（离线演示）；local = 联调 web/backend 统一服务端（http://127.0.0.1:5193）；
 * docker = H5 由 mobile/Dockerfile 的 nginx 同源托管（/api/v1 反代到 5193）。 */
export const CURRENT_ENV: EnvConfig['name'] = 'local'

export const env: EnvConfig = ENVS[CURRENT_ENV]

export const APP_INFO = {
  name: '邻里小栈',
  slogan: '真实邻居 · 安心流转',
  version: '1.0.0',
  agreementUrl: 'https://www.neighinn.com/legal/user-agreement',
  privacyUrl: 'https://www.neighinn.com/legal/privacy',
  publishRuleUrl: 'https://www.neighinn.com/legal/publish-rule',
  supportPhone: '400-800-2026',
}
