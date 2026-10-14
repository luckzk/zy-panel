import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发时把 API 与 WebSocket 转发到本地后端，免去跨域配置
      '/api/v1': {
        target: 'http://localhost:8818',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8818',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
