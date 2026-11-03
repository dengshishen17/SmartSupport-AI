import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发环境把 /ai 开头的请求转发到后端 8080，避免跨域问题（后端无需改动）
      '/ai': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        // SSE 流式响应不能被代理缓冲，确保逐 chunk 透传给浏览器
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
              proxyRes.headers['connection'] = 'keep-alive'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
      // 业务接口（订单/退款/工单）转发到后端 8080
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})