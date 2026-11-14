import { ref } from 'vue'
import { env } from '../config/env'
import { presignUpload } from '../api/config.api'
import { chooseImages, chooseVideo, compressImage } from '../utils/image'

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

  async function uploadOne(path: string): Promise<string> {
    const fileName = path.split('/').pop() ?? `image-${Date.now()}.jpg`
    if (env.mock || /^https?:\/\//.test(path)) {
      progress.value = 100
      return path
    }
    uploading.value = true
    progress.value = 0
    try {
      const presign = await presignUpload({ fileName, fileType: 'image/jpeg' })
      await new Promise<void>((resolve, reject) => {
        const task = uni.uploadFile({
          url: presign.uploadUrl,
          filePath: path,
          name: 'file',
          header: presign.headers,
          success: (res: any) => {
            if (res.statusCode >= 200 && res.statusCode < 300) resolve()
            else reject(new Error('上传失败'))
          },
          fail: reject,
        })
        if (task && typeof task.onProgressUpdate === 'function') {
          task.onProgressUpdate((event: any) => {
            progress.value = event.progress ?? 0
          })
        }
      })
      return presign.fileUrl
    } finally {
      uploading.value = false
    }
  }

  async function uploadMany(paths: string[]): Promise<string[]> {
    const urls: string[] = []
    for (const path of paths) {
      urls.push(await uploadOne(path))
    }
    return urls
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
