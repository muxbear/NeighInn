/** 图片/视频选择、压缩、预览统一封装 */

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

export function chooseVideo(options: { maxDuration?: number } = {}): Promise<{ path: string; duration: number; size: number }> {
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
        })
      },
      fail: (err: any) => reject(err),
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

export const PLACEHOLDER_IMAGE = '/static/placeholders/item-placeholder.svg'
export const ERROR_IMAGE = '/static/placeholders/image-error.svg'
