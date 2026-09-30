import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 负责把 React + TypeScript 代码打包成浏览器能跑的 HTML/JS
export default defineConfig({
  plugins: [react()],
  // 关键：Electron 生产环境用 file:// 加载页面，
  // 必须让资源路径变成相对的 ./assets/...，否则会白屏
  base: './',
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
