import { moduleRouteAccess } from '~/utils/moduleActivation'
import type { ActiveModule, ApiResponse } from '~/types'

export default defineNuxtRouteMiddleware(async (to) => {
  if (typeof to.meta.dentalpinModule !== 'string') return

  const auth = useAuth()
  let activeModules: Array<{ name: string }> | null = null
  if (auth.accessToken.value) {
    const active = useState<ActiveModule[] | null>('modules:active', () => null)
    const error = useState<string | null>('modules:active:error', () => null)
    const lastLoadedAt = useState<number>('modules:active:at', () => 0)
    const config = useRuntimeConfig()
    const baseURL = import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
    try {
      const response = await $fetch<ApiResponse<ActiveModule[]>>('/api/v1/modules/-/active', {
        baseURL,
        headers: { Authorization: `Bearer ${auth.accessToken.value}` }
      })
      active.value = response.data
      error.value = null
      lastLoadedAt.value = Date.now()
    } catch (err) {
      active.value = null
      error.value = err instanceof Error ? err.message : 'Failed to load modules'
    }
    activeModules = active.value
  } else {
    const config = useRuntimeConfig()
    const baseURL = import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
    try {
      const response = await $fetch<{ data: string[] }>('/api/v1/modules/-/active-names', {
        baseURL
      })
      activeModules = response.data.map(name => ({ name }))
    } catch {
      activeModules = null
    }
  }

  const access = moduleRouteAccess(to.meta, activeModules)
  if (access === 'inactive') {
    return abortNavigation(createError({
      statusCode: 404,
      statusMessage: 'Module is not installed'
    }))
  }
  if (access === 'unavailable') {
    return abortNavigation(createError({
      statusCode: 503,
      statusMessage: 'Module activation state is unavailable'
    }))
  }
})
