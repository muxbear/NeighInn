import { ref } from 'vue'
import { env } from '../config/env'
import { ApiError } from '../api/errors'
import { secureStorage } from '../utils/storage'
import { createIdempotencyKey } from '../utils/idempotency'
import { chooseImages, chooseVideo, compressImage } from '../utils/image'

export type UploadScene = 'REALNAME_ID' | 'OWNER_PROOF' | 'ITEM_IMAGE' | 'PUBLIC_IMAGE' | 'LIFE_VIDEO'

function contentTypeOf(path: string): string {
  const ext = (path.split('.').pop() ?? '').toLowerCase()
  if (ext === 'png') return 'image/png'
  if (ext === 'webp') return 'image/webp'
  if (ext === 'mp4' || ext === 'm4v') return 'video/mp4'
  if (ext === 'mov') return 'video/quicktime'
  if (ext === 'webm') return 'video/webm'
  return 'image/jpeg'
}

function extensionOf(type: string): string {
  if (type === 'image/png') return '.png'
  if (type === 'image/webp') return '.webp'
  if (type === 'application/pdf') return '.pdf'
  if (type === 'video/mp4') return '.mp4'
  if (type === 'video/quicktime') return '.mov'
  if (type === 'video/webm') return '.webm'
  return '.jpg'
}

function isH5Runtime(): boolean {
  return typeof window !== 'undefined'
    && typeof document !== 'undefined'
    && typeof FormData !== 'undefined'
    && typeof fetch === 'function'
}

function parseUploadResponse(statusCode: number, raw: any): { body: any; ok: boolean } {
  let body: any = raw
  if (typeof raw === 'string') {
    try {
      body = JSON.parse(raw)
    } catch {
      body = null
    }
  }
  return {
    body,
    ok: statusCode >= 200 && statusCode < 300 && body?.code === 0,
  }
}

/** fetch 的网络级失败（DNS/断网/blob 失效）统一转成可读的 ApiError。 */
async function fetchOrApiError(
  input: string,
  init: RequestInit | undefined,
  message: string,
): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch {
    throw new ApiError(50000, message)
  }
}

// 单文件上限 10MB（服务端 MAX_IMAGE_UPLOAD_BYTES）。华为/iPhone 原图常见 8–20MB，
// H5 的 sizeType:'compressed' 不生效，这里在浏览器端先等比缩放再上传。
const IMAGE_UPLOAD_LIMIT_BYTES = 10 * 1024 * 1024
const IMAGE_SHRINK_TARGET_BYTES = 3 * 1024 * 1024

async function shrinkImageForUpload(blob: Blob, scene: UploadScene): Promise<Blob> {
  if (typeof document === 'undefined' || typeof createImageBitmap !== 'function') return blob
  if (!blob.type.startsWith('image/') || blob.type === 'image/gif') return blob
  if (blob.size <= IMAGE_SHRINK_TARGET_BYTES) return blob
  // 认证材料要能看清证件号，保留更高分辨率；物品图/生活图 1600px 足够。
  const isCert = scene === 'REALNAME_ID' || scene === 'OWNER_PROOF'
  const maxSide = isCert ? 2400 : 1600
  const quality = isCert ? 0.9 : 0.82
  try {
    const bitmap = await createImageBitmap(blob)
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
    const width = Math.max(1, Math.round(bitmap.width * scale))
    const height = Math.max(1, Math.round(bitmap.height * scale))
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return blob
    ctx.drawImage(bitmap, 0, 0, width, height)
    if (typeof bitmap.close === 'function') bitmap.close()
    const resized = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', quality)
    })
    // 压缩后反而更大（小图或已高度压缩）时用原图。
    return resized && resized.size > 0 && resized.size < blob.size ? resized : blob
  } catch {
    return blob
  }
}

function uploadError(statusCode: number, body: any): ApiError {
  return new ApiError(
    Number(body?.code) || 50000,
    statusCode === 404
      ? '上传接口未找到，请重启后端服务后重试'
      : (body?.message || '材料上传失败'),
    body?.traceId || '',
    statusCode,
  )
}

export function useUpload() {
  const uploading = ref(false)
  const progress = ref(0)

  async function chooseAndPrepare(count = 9): Promise<string[]> {
    const paths = await chooseImages({ count })
    const compressed: string[] = []
    for (const path of paths) {
      compressed.push(await compressImage(path, 82))
    }
    return compressed
  }

  async function prepareVideo(): Promise<string> {
    const video = await chooseVideo({ maxDuration: env.mock ? 180 : 180 })
    return video.path
  }

  async function uploadOne(path: string, scene: UploadScene = 'PUBLIC_IMAGE'): Promise<string> {
    if (env.mock) {
      progress.value = 100
      return `mock/certifications/${scene.toLowerCase()}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.jpg`
    }
    if (/^https?:\/\//.test(path)) return path

    uploading.value = true
    progress.value = 0
    try {
      const token = secureStorage.getAccessToken()
      const uploadUrl = `${env.uploadUrl}/uploads`
      const idempotencyKey = createIdempotencyKey('upload')

      // H5 的 uni.uploadFile 对 blob: 临时地址会提交 0 字节文件，
      // 改用 fetch + FormData 上传；App/小程序仍使用 uni.uploadFile。
      if (isH5Runtime()) {
        const source = await fetchOrApiError(
          path, undefined, '照片已失效，请重新选择照片后提交')
        if (!source.ok) {
          throw new ApiError(40001, '图片读取失败，请重新选择')
        }
        const raw = await source.blob()
        if (!raw.size) {
          throw new ApiError(40001, '图片内容为空，请重新选择')
        }
        const blob = await shrinkImageForUpload(raw, scene)
        if (blob.size > IMAGE_UPLOAD_LIMIT_BYTES) {
          throw new ApiError(41301, '照片超过 10MB，请重新选择较小的照片')
        }
        const fileName = `upload-${Date.now()}${extensionOf(blob.type || contentTypeOf(path))}`
        const form = new FormData()
        form.append('scene', scene)
        form.append('file', blob, fileName)
        const response = await fetchOrApiError(
          uploadUrl,
          {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
            'X-Idempotency-Key': idempotencyKey,
          },
          body: form,
          },
          '网络异常，照片上传失败，请检查网络后重试',
        )
        const { body, ok } = parseUploadResponse(response.status, await response.text())
        if (!ok) throw uploadError(response.status, body)
        progress.value = 100
        return String(body?.data?.objectKey ?? '')
      }

      // App/小程序：uni.uploadFile 直接读本地路径，先压缩一遍，避免原图超过 10MB 被服务端拒绝。
      const isCertScene = scene === 'REALNAME_ID' || scene === 'OWNER_PROOF'
      const uploadPath = await compressImage(path, isCertScene ? 92 : 80)
      return await new Promise<string>((resolve, reject) => {
        const task = uni.uploadFile({
          url: uploadUrl,
          filePath: uploadPath,
          name: 'file',
          header: {
            Authorization: `Bearer ${token}`,
            'X-Idempotency-Key': idempotencyKey,
          },
          formData: {
            scene,
          },
          success: (res: any) => {
            const { body, ok } = parseUploadResponse(res.statusCode, res.data)
            if (ok) {
              progress.value = 100
              resolve(String(body?.data?.objectKey ?? ''))
              return
            }
            reject(uploadError(res.statusCode, body))
          },
          fail: (error: any) => {
            reject(new ApiError(50000, error?.errMsg || '网络连接失败，请检查网络'))
          },
        })
        if (task && typeof task.onProgressUpdate === 'function') {
          task.onProgressUpdate((event: any) => {
            progress.value = event.progress ?? 0
          })
        }
      })
    } finally {
      uploading.value = false
    }
  }

  async function uploadMany(paths: string[], scene: UploadScene = 'PUBLIC_IMAGE'): Promise<string[]> {
    const keys: string[] = []
    for (const path of paths) {
      keys.push(await uploadOne(path, scene))
    }
    return keys
  }

  return {
    uploading,
    progress,
    chooseAndPrepare,
    prepareVideo,
    uploadOne,
    uploadMany,
  }
}
