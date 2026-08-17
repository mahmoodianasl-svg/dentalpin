import { beforeEach } from 'vitest'
import { computed, readonly, ref, unref } from 'vue'

const stateStore = new Map<string, { value: unknown }>()
const cookieStore = new Map<string, { value: unknown }>()

function state<T>(key: string, init: () => T) {
  if (!stateStore.has(key)) stateStore.set(key, ref(init()) as { value: unknown })
  return stateStore.get(key) as { value: T }
}

function cookie<T = string | null>(key: string) {
  if (!cookieStore.has(key)) cookieStore.set(key, ref(null) as { value: unknown })
  return cookieStore.get(key) as { value: T }
}

Object.assign(globalThis, {
  computed,
  readonly,
  unref,
  useState: state,
  useCookie: cookie,
  useRuntimeConfig: () => ({
    apiBaseUrlServer: 'http://localhost:8000',
    public: { apiBaseUrl: 'http://localhost:8000' }
  }),
  useRouter: () => ({ push: async () => undefined }),
  useI18n: () => ({ t: (key: string) => key }),
  usePermissions: () => ({ can: () => true }),
  $fetch: async () => {
    throw new Error('Unexpected network request in unit test')
  }
})

beforeEach(() => {
  stateStore.clear()
  cookieStore.clear()
})
