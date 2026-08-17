import { fileURLToPath } from 'node:url'
import { defineVitestProject } from '@nuxt/test-utils/config'
import { defineConfig } from 'vitest/config'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))
const appRoot = fileURLToPath(new URL('./app', import.meta.url))

export default defineConfig({
  test: {
    projects: [
      {
        resolve: {
          alias: {
            '~': appRoot,
            '@': appRoot,
            '~~': frontendRoot,
            '@@': frontendRoot
          }
        },
        test: {
          name: 'unit',
          globals: true,
          environment: 'node',
          include: [
            'tests/agenda/**/*.{test,spec}.ts',
            'tests/components/**/*.{test,spec}.ts',
            'tests/config/**/*.{test,spec}.ts',
            'tests/utils/**/*.{test,spec}.ts',
            'tests/types.test.ts'
          ]
        }
      },
      await defineVitestProject({
        test: {
          name: 'nuxt',
          globals: true,
          include: ['tests/composables/**/*.{test,spec}.ts'],
          environment: 'nuxt',
          environmentOptions: {
            nuxt: {
              rootDir: frontendRoot,
              domEnvironment: 'happy-dom',
              mock: {
                intersectionObserver: true,
                indexedDb: true
              }
            }
          }
        }
      })
    ]
  }
})
