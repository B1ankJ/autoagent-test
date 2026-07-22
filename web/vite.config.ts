import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const rootDir = new URL('.', import.meta.url)

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(rootDir.pathname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: path.resolve(rootDir.pathname, '../src/autoagent/static'),
    emptyOutDir: true,
    // Keep the initial JS payload small: split heavy vendors into their
    // own chunks so the Dashboard/Batches first paint doesn't pull Monaco.
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('monaco-editor') || id.includes('@monaco-editor')) {
            return 'monaco'
          }
          if (id.includes('/antd/') || id.includes('@ant-design/')) {
            return 'antd'
          }
          if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('scheduler')) {
            return 'react'
          }
          return undefined
        },
      },
    },
    chunkSizeWarningLimit: 1500,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Default (5000ms) is too tight for Builder.test.tsx's heaviest flows
    // on GitHub Actions' shared runners (~3x slower than local) — a
    // vi.setConfig({ testTimeout }) call in that file's beforeAll did not
    // reliably apply (still hit the 5000ms default in CI), so set it here
    // instead, where it's read once at startup with no ordering ambiguity.
    testTimeout: 20000,
  },
})
