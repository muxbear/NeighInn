/**
 * 环境配置。
 * 当前无后端联调环境，默认开启 Mock；接入真实网关时把 mock 改为 false，并替换 baseUrl / wsUrl。
 */
export interface EnvConfig {
  name: 'dev' | 'test' | 'staging' | 'prod'
  baseUrl: string
  wsUrl: string
  uploadUrl: string
  mock: boolean
  mockLatency: number
  requestTimeout: number
}

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

/** 切换环境：改这里即可；HBuilderX 发版前务必确认为 staging / prod。 */
export const CURRENT_ENV: EnvConfig['name'] = 'dev'

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
