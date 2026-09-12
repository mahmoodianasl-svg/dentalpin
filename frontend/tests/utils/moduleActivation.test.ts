import { describe, expect, it } from 'vitest'
import type { ActiveModule } from '~/types'
import { moduleRouteAccess } from '~/utils/moduleActivation'

const active: ActiveModule[] = [{
  name: 'reports',
  version: '1.0.0',
  category: 'official',
  summary: 'Reports',
  navigation: [],
  permissions: []
}]

describe('module route activation boundary', () => {
  it('leaves host routes outside the module gate', () => {
    expect(moduleRouteAccess({}, null)).toBe('host')
  })

  it('allows only routes owned by an installed module', () => {
    expect(moduleRouteAccess({ dentalpinModule: 'reports' }, active)).toBe('active')
    expect(moduleRouteAccess({ dentalpinModule: 'patient_agent' }, active)).toBe('inactive')
  })

  it('fails closed while persisted activation state is unavailable', () => {
    expect(moduleRouteAccess({ dentalpinModule: 'reports' }, null)).toBe('unavailable')
  })
})
