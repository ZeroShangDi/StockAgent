import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

function resolveGitValue(command: string, fallback: string): string {
  try {
    return execSync(command, { encoding: 'utf-8' }).trim() || fallback
  } catch {
    return fallback
  }
}

const buildTime = new Date().toISOString()
const commitSha = process.env.GITHUB_SHA || resolveGitValue('git rev-parse HEAD', 'local')
const shortSha = commitSha.slice(0, 7)
const branch = process.env.GITHUB_REF_NAME || resolveGitValue('git rev-parse --abbrev-ref HEAD', 'local')
const buildId = `${shortSha}-${buildTime}`
const buildInfo = {
  buildId,
  buildTime,
  commitSha,
  branch,
}

function buildInfoPlugin() {
  return {
    name: 'stockagent-build-info',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'version.json',
        source: JSON.stringify(buildInfo, null, 2),
      })
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    buildInfoPlugin(),
    // 自动导入 Vue/VueRouter/Pinia API
    AutoImport({
      imports: ['vue', 'vue-router', 'pinia'],
      resolvers: [ElementPlusResolver()],
      dts: 'src/auto-imports.d.ts',
    }),
    // 自动导入 Element Plus 组件
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  define: {
    __APP_BUILD_INFO__: JSON.stringify(buildInfo),
  },
  css: {
    preprocessorOptions: {
      scss: {
        // 使用新的 Sass API 消除弃用警告
        api: 'modern-compiler',
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      // API 代理
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // WebSocket 代理
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
    allowedHosts: [
      'localhost',
      'qibalili.cn',
      'og824md55716.vicp.fun',
      '.qibalili.cn'  // 允许所有子域名
    ]
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'element-plus': ['element-plus'],
          'echarts': ['echarts', 'vue-echarts'],
          'vendor': ['vue', 'vue-router', 'pinia', 'axios'],
        },
      },
    },
  },
})
