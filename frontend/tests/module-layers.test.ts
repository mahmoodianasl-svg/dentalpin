import { describe, expect, it } from 'vitest'
import { annotateModulePages, type ModulePage } from '../module-layers'

describe('production module layer ownership', () => {
  it('marks module-owned routes, including nested pages, without marking host routes', () => {
    const pages: ModulePage[] = [
      { file: '/app/app/pages/index.vue' },
      {
        file: '/module_layers/patient_agent/frontend/pages/ai.vue',
        children: [
          { file: '/module_layers/patient_agent/frontend/pages/ai/knowledge.vue' }
        ]
      }
    ]

    annotateModulePages(pages, [
      { name: 'patient_agent', path: '/module_layers/patient_agent/frontend' }
    ])

    expect(pages[0].meta).toBeUndefined()
    expect(pages[1].meta?.dentalpinModule).toBe('patient_agent')
    expect(pages[1].children?.[0].meta?.dentalpinModule).toBe('patient_agent')
  })

  it('does not confuse sibling paths with a module root', () => {
    const pages: ModulePage[] = [
      { file: '/module_layers/reports_extra/frontend/pages/index.vue' }
    ]

    annotateModulePages(pages, [
      { name: 'reports', path: '/module_layers/reports/frontend' }
    ])

    expect(pages[0].meta).toBeUndefined()
  })
})
