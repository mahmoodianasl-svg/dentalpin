import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))
const appRoot = fileURLToPath(new URL('./app', import.meta.url))

export default defineConfig({
  resolve: {
    alias: {
      '~': appRoot,
      '@': appRoot,
      '~~': frontendRoot,
      '@@': frontendRoot
    }
  },
  test: {
    globals: true,
    environment: 'node',
    setupFiles: ['tests/setup/unit.ts'],
    include: ['tests/**/*.{test,spec}.ts'],
    exclude: ['**/node_modules/**', '**/dist/**', 'tests/e2e/**']
  }
})
