export type ModuleRouteAccess = 'host' | 'active' | 'inactive' | 'unavailable'

export function moduleRouteAccess(
  meta: Record<string, unknown>,
  activeModules: Array<{ name: string }> | null
): ModuleRouteAccess {
  const owner = meta.dentalpinModule
  if (typeof owner !== 'string' || !owner) return 'host'
  if (activeModules === null) return 'unavailable'
  return activeModules.some(module => module.name === owner) ? 'active' : 'inactive'
}
