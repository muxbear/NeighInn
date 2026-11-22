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
        const blob = await source.blob()
        if (!blob.size) {
          throw new ApiError(40001, '图片内容为空，请重新选择')
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

      return await new Promise<string>((resolve, reject) => {
        const task = uni.uploadFile({
          url: uploadUrl,
          filePath: path,
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
