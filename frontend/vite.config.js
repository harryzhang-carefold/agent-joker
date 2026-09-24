import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// S10 WebConsole：vite dev 反代 /api /v1 /mcp → BFF（S08，默认 127.0.0.1:8000）。
// 生产由 nginx 托管 dist + 反代同一组前缀（ARCH §5.1 / deploy/nginx）。
// 可用环境变量 BFF_TARGET 覆盖后端地址（如连别的 BFF 实例）。
const BFF_TARGET = process.env.BFF_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: BFF_TARGET, changeOrigin: true, ws: true },
      '/v1': { target: BFF_TARGET, changeOrigin: true, ws: true },
      '/mcp': { target: BFF_TARGET, changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element'
            if (id.includes('vue') || id.includes('pinia')) return 'vendor-vue'
            return 'vendor'
          }
        },
      },
    },
  },
})
