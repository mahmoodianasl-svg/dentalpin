import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { SemanticRole } from '~/config/severity'

describe('useEntityStatus composable', () => {
  it('should export useEntityStatus function', async () => {
    const module = await import('~/composables/useEntityStatus')
    expect(module.useEntityStatus).toBeDefined()
    expect(typeof module.useEntityStatus).toBe('function')
  })

  it('should map status to semantic role via the provided map', async () => {
    const { useEntityStatus } = await import('~/composables/useEntityStatus')

    const roleMap: Record<'draft' | 'issued', SemanticRole> = {
      draft: 'neutral',
      issued: 'info'
    }
    const status = ref<'draft' | 'issued'>('issued')

    const { role } = useEntityStatus(status, roleMap, 'invoice.status')

    expect(role.value).toBe('info')
    status.value = 'draft'
    expect(role.value).toBe('neutral')
  })

  it('should translate "danger" role to "error" UI colour', async () => {
    const { useEntityStatus } = await import('~/composables/useEntityStatus')

    const { uiColor } = useEntityStatus(
      ref('rejected'),
      { rejected: 'danger' as SemanticRole },
      'invoice.status'
    )

    expect(uiColor.value).toBe('error')
  })

  it('should fall back to neutral when status is missing from map', async () => {
    const { useEntityStatus } = await import('~/composables/useEntityStatus')

    const { role } = useEntityStatus(
      ref('unknown'),
      { known: 'success' as SemanticRole },
      'invoice.status'
    )

    expect(role.value).toBe('neutral')
  })

  it('should fall back to neutral and empty label when status is null', async () => {
    const { useEntityStatus } = await import('~/composables/useEntityStatus')

    const { role, label } = useEntityStatus(
      ref(null),
      {} as Record<string, SemanticRole>,
      'invoice.status'
    )

    expect(role.value).toBe('neutral')
    expect(label.value).toBe('')
  })
})
