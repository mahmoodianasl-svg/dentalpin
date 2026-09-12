import { readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'

export interface ModuleLayerEntry {
  name: string
  path: string
}

export interface ModulePage {
  file?: string
  meta?: Record<string, unknown>
  children?: ModulePage[]
}

export function loadModuleLayerEntries(configPath: string): ModuleLayerEntry[] {
  const raw = readFileSync(configPath, 'utf-8')
  const payload = JSON.parse(raw) as { modules?: unknown }
  if (!Array.isArray(payload.modules)) return []

  return payload.modules.filter((entry): entry is ModuleLayerEntry => {
    if (!entry || typeof entry !== 'object') return false
    const candidate = entry as Record<string, unknown>
    return typeof candidate.name === 'string' && typeof candidate.path === 'string'
  })
}

export function annotateModulePages(
  pages: ModulePage[],
  moduleLayers: readonly ModuleLayerEntry[]
): void {
  const roots = moduleLayers.map(entry => ({
    name: entry.name,
    path: resolve(entry.path)
  }))

  function annotate(entries: ModulePage[]): void {
    for (const page of entries) {
      if (page.file) {
        const file = resolve(page.file)
        const owner = roots.find(root => file === root.path || file.startsWith(`${root.path}${sep}`))
        if (owner) {
          page.meta = { ...page.meta, dentalpinModule: owner.name }
        }
      }
      if (page.children) annotate(page.children)
    }
  }

  annotate(pages)
}
