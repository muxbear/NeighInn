/** 图片/视频选择、压缩、预览统一封装 */

import { env } from '../config/env'

export interface ChooseImageOptions {
  count?: number
  sourceType?: Array<'album' | 'camera'>
  sizeType?: Array<'original' | 'compressed'>
}

export function chooseImages(options: ChooseImageOptions = {}): Promise<string[]> {
  const count = Math.max(1, Math.min(options.count ?? 9, 12))
  return new Promise((resolve, reject) => {
    if (typeof uni === 'undefined') {
      reject(new Error('当前环境不支持选择图片'))
      return
    }
    uni.chooseImage({
      count,
      sizeType: options.sizeType ?? ['compressed'],
      sourceType: options.sourceType ?? ['album', 'camera'],
      success: (res: any) => {
        const paths: string[] = res.tempFilePaths ?? []
        resolve(paths)
      },
      fail: (err: any) => reject(err),
    })
  })
}

export interface ChosenVideo {
  path: string
  duration: number
  size: number
  width: number
  height: number
}

export function chooseVideo(options: { maxDuration?: number } = {}): Promise<ChosenVideo> {
  return new Promise((resolve, reject) => {
    if (typeof uni === 'undefined') {
      reject(new Error('当前环境不支持选择视频'))
      return
    }
    uni.chooseVideo({
      sourceType: ['album', 'camera'],
      compressed: true,
      maxDuration: options.maxDuration ?? 180,
      success: (res: any) => {
        resolve({
          path: res.tempFilePath,
          duration: res.duration ?? 0,
          size: res.size ?? 0,
          width: res.width ?? 0,
          height: res.height ?? 0,
        })
      },
      fail: (err: any) => reject(err),
    })
  })
}

/** 读取本地图片宽高（用于聊天气泡按原始比例展示）；失败时返回 null。 */
export function getImageInfo(src: string): Promise<{ width: number; height: number } | null> {
  return new Promise((resolve) => {
    if (typeof uni === 'undefined' || typeof uni.getImageInfo !== 'function') {
      resolve(null)
      return
    }
    uni.getImageInfo({
      src,
      success: (res: any) => resolve({
        width: Number(res?.width) || 0,
        height: Number(res?.height) || 0,
      }),
      fail: () => resolve(null),
    })
  })
}

export function compressImage(src: string, quality = 80): Promise<string> {
  return new Promise((resolve) => {
    if (typeof uni === 'undefined' || typeof uni.compressImage !== 'function') {
      resolve(src)
      return
    }
    uni.compressImage({
      src,
      quality,
      success: (res: any) => resolve(res.tempFilePath ?? src),
      fail: () => resolve(src),
    })
  })
}

export function previewImages(urls: string[], current?: string): void {
  if (!urls.length || typeof uni === 'undefined') return
  uni.previewImage({
    urls,
    current: current ?? urls[0],
  })
}

export function isRemoteUrl(url: string): boolean {
  return /^https?:\/\//.test(String(url || ''))
}

/**
 * 媒体地址归一化：
 * - 本地临时文件 / data / blob / 绝对 URL 原样返回；
 * - 服务端下发的同源相对地址（/api/v1/media/...）在本地联调时补后端主机；
 * - 历史数据中的裸对象键兜底拼成 /media/<key>。
 */
export function resolveMediaUrl(url?: string | null): string {
  const value = String(url || '').trim()
  if (!value) return ''
  // App/小程序本地临时文件（_doc/_www/wxfile 等）与完整 URL 原样返回。
  if (/^(https?:|data:|blob:|file:|wxfile:|_doc|_www|_downloads|\/\/)/.test(value)) return value
  if (value.startsWith('/')) {
    // 只取协议+主机，兼容 baseUrl 的 /api/v1 与 /v1 两种前缀。
    const origin = env.baseUrl.match(/^(https?:\/\/[^/]+)/)
    return origin ? `${origin[1]}${value}` : value
  }
  const key = value.replace(/^\/+/, '')
  const origin = env.baseUrl.match(/^(https?:\/\/[^/]+)/)
  return origin
    ? `${origin[1]}/api/v1/media/${key}`
    : `${env.baseUrl.replace(/\/$/, '')}/media/${key}`
}

export const PLACEHOLDER_IMAGE = '/static/placeholders/item-placeholder.svg'
export const ERROR_IMAGE = '/static/placeholders/image-error.svg'
