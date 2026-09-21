import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => vi.unstubAllGlobals())

describe('useAuth composable', () => {
  describe('initialization', () => {
    it('should export useAuth function', async () => {
      const module = await import('~/composables/useAuth')
      expect(module.useAuth).toBeDefined()
      expect(typeof module.useAuth).toBe('function')
    })
  })

  describe('returned interface', () => {
    it('should return expected properties', async () => {
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      // Check returned properties exist
      expect(auth).toHaveProperty('user')
      expect(auth).toHaveProperty('accessToken')
      expect(auth).toHaveProperty('isAuthenticated')
      expect(auth).toHaveProperty('login')
      expect(auth).toHaveProperty('logout')
      expect(auth).toHaveProperty('refresh')
      expect(auth).toHaveProperty('fetchUser')
      expect(auth).toHaveProperty('init')
    })

    it('should have login as an async function', async () => {
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      expect(typeof auth.login).toBe('function')
    })

    it('should have logout as an async function', async () => {
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      expect(typeof auth.logout).toBe('function')
    })

    it('should have refresh as an async function', async () => {
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      expect(typeof auth.refresh).toBe('function')
    })
  })

  describe('initial state', () => {
    it('should not be authenticated initially', async () => {
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      // Without tokens, should not be authenticated
      expect(auth.isAuthenticated.value).toBe(false)
    })

    it('should have null user initially', async () => {
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      expect(auth.user.value).toBe(null)
    })
  })

  describe('MFA login and enrollment', () => {
    it('returns a one-time replacement after recovery login even if profile loading fails', async () => {
      const request = vi.fn()
        .mockResolvedValueOnce({ access_token: 'verified-session', replacement_recovery_code: 'new-code' })
        .mockRejectedValueOnce(new Error('Profile temporarily unavailable'))
      vi.stubGlobal('$fetch', request)
      const log = vi.spyOn(console, 'error').mockImplementation(() => undefined)
      try {
        const { useAuth } = await import('~/composables/useAuth')
        const auth = useAuth()
        expect(await auth.completeMfa('challenge', 'used-code')).toBe('new-code')
        expect(auth.accessToken.value).toBe('verified-session')
      } finally {
        log.mockRestore()
      }
    })

    it('keeps a pending password challenge out of authenticated state', async () => {
      const request = vi.fn().mockResolvedValue({ mfa_required: true, challenge: 'pending-secret' })
      vi.stubGlobal('$fetch', request)
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()

      expect(await auth.login({ email: 'staff@example.test', password: 'password' }))
        .toEqual({ mfa_required: true, challenge: 'pending-secret' })
      expect(auth.accessToken.value).toBeNull()
      expect(auth.isAuthenticated.value).toBe(false)
      expect(request).toHaveBeenCalledTimes(1)
    })

    it('returns one-time recovery codes even if the profile fetch fails', async () => {
      const request = vi.fn()
        .mockResolvedValueOnce({ access_token: 'password-session' })
        .mockResolvedValueOnce({ data: { user: { id: 'staff' }, permissions: [] } })
        .mockResolvedValueOnce({ access_token: 'verified-session', recovery_codes: ['save-me'] })
        .mockRejectedValueOnce(new Error('Profile temporarily unavailable'))
      vi.stubGlobal('$fetch', request)
      const log = vi.spyOn(console, 'error').mockImplementation(() => undefined)
      try {
        const { useAuth } = await import('~/composables/useAuth')
        const auth = useAuth()
        await auth.login({ email: 'staff@example.test', password: 'password' })

        expect(await auth.confirmMfaEnrollment('challenge', '123456')).toEqual(['save-me'])
        expect(auth.accessToken.value).toBe('verified-session')
      } finally {
        log.mockRestore()
      }
    })

    it('replaces recovery codes using the in-memory access token', async () => {
      const request = vi.fn()
        .mockResolvedValueOnce({ access_token: 'verified-session' })
        .mockResolvedValueOnce({ data: { user: { id: 'staff' }, permissions: [] } })
        .mockResolvedValueOnce({ recovery_codes: ['new-code'] })
      vi.stubGlobal('$fetch', request)
      const { useAuth } = await import('~/composables/useAuth')
      const auth = useAuth()
      await auth.login({ email: 'staff@example.test', password: 'password' })

      expect(await auth.rotateMfaRecoveryCodes('password', '123456')).toEqual(['new-code'])
      expect(request).toHaveBeenLastCalledWith('/api/v1/auth/mfa/recovery/rotate',
        expect.objectContaining({
          body: { password: 'password', code: '123456' },
          headers: { Authorization: 'Bearer verified-session' }
        }))
      expect(auth.accessToken.value).toBe('verified-session')
    })
  })
})
