import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Приложение живёт по адресу /journals/ на домене платформы. API журналов — /journals/api/v1
// (nginx платформы срезает /journals и отдаёт в journals_api). На стенде разработчика запросы
// /journals/api уходят в API журналов на localhost:8000.
export default defineConfig({
  base: '/journals/',
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    proxy: {
      '/journals/api': {
        target: process.env.JOURNALS_API ?? 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/journals/, ''),
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
