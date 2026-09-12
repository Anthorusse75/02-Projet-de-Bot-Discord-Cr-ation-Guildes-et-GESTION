import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.DID_DEV_BACKEND_ORIGIN || 'http://127.0.0.1:8001'
  const wsBackend = backend.replace(/^http/, 'ws')

  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 8000,
      strictPort: true,
      proxy: {
        '/api': { target: backend, changeOrigin: true },
        '/auth': { target: backend, changeOrigin: true },
        '/health': { target: backend, changeOrigin: true },
        '/ws': { target: wsBackend, ws: true, changeOrigin: true },
      },
    },
  }
})
