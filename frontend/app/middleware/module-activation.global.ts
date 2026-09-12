import { moduleRouteAccess } from '~/utils/moduleActivation'

export default defineNuxtRouteMiddleware(async (to) => {
  if (typeof to.meta.dentalpinModule !== 'string') return

  const auth = useAuth()
  let activeModules: Array<{ name: string }> | null = null
  if (auth.accessToken.value) {
    const modules = useModules()
    await modules.ensureLoaded()
    activeModules = modules.active.value
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
