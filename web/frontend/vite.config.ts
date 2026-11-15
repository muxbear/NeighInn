import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const backendDir = fileURLToPath(new URL('../backend', import.meta.url))
  const backendEnv = loadEnv(mode, backendDir, '')
  const backendHost = backendEnv.APP_HOST || '127.0.0.1'
  const proxyHost = backendHost === '0.0.0.0' ? '127.0.0.1' : backendHost
  const backendPort = backendEnv.APP_PORT || '5193'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5192,
      proxy: {
        '/api': {
          // 与 web/backend/.env 的监听地址保持一致，仅用于 Vite 服务端代理。
          target: `http://${proxyHost}:${backendPort}`,
          changeOrigin: true,
        },
      },
    },
  }
})
