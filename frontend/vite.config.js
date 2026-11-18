import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时 Vite 跑在 5173，接口和图片都代理到 FastAPI（8000），避免跨域。
// 生产构建输出 frontend/dist，由 FastAPI 在根路径托管。
//
// Element Plus 不走自动引入插件：见 src/plugins/element-components.js 的说明。
export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  // 演示版把录好的 fixture 和图片放在 demo-public/，正常构建不带上它们
  publicDir: mode === 'demo' ? 'demo-public' : 'public',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/media': 'http://127.0.0.1:8000',
    },
  },
  build: {
    // 演示版（离线快照）输出到独立目录，别覆盖 API 直接托管的 dist
    outDir: mode === 'demo' ? 'dist-demo' : 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // vis-network 与 echarts 各自体积都很大，拆成独立 chunk：
        // 一是首包不至于被它们拖慢，二是它们很少变动，浏览器缓存命中率高。
        manualChunks(id) {
          if (id.includes('node_modules/vis-network') || id.includes('node_modules/vis-data')
              || id.includes('node_modules/vis-util') || id.includes('node_modules/hammerjs')) {
            return 'vendor-graph'
          }
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) {
            return 'vendor-charts'
          }
          if (id.includes('node_modules/element-plus') || id.includes('node_modules/@element-plus')) {
            return 'vendor-element'
          }
          if (id.includes('node_modules/lodash-es') || id.includes('node_modules/@vueuse')) {
            return 'vendor-element'
          }
          if (id.includes('node_modules/vue')) return 'vendor-vue'
          return undefined
        },
      },
    },
  },
}))
