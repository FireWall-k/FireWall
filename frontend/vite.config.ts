import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    // e2e/는 Playwright 테스트(실제 브라우저)다. vitest가 *.spec.ts로 집어 jsdom에서 돌리지 않게 뺀다.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
