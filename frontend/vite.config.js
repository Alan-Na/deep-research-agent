import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API_TARGET = process.env.VITE_API_TARGET || process.env.VITE_API_BASE_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/research-jobs': { target: API_TARGET, changeOrigin: true },
      '/reports':        { target: API_TARGET, changeOrigin: true },
      '/analyze':        { target: API_TARGET, changeOrigin: true },
    },
  },
})
