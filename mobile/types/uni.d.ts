/**
 * uni-app x 运行时全局能力的宽松声明。
 * 仅服务于纯 TS 逻辑的 tsc / Vitest 校验；.uvue 的实际类型以 HBuilderX 编译为准。
 */
declare const uni: any
declare const plus: any
declare const getCurrentPages: () => any[]
declare const getApp: () => any

interface ImportMetaEnv {
  readonly MODE: string
  readonly DEV: boolean
  readonly PROD: boolean
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
