import type {
  User,
  LoginCredentials,
  AccessTokenResponse,
  AuthResponse,
  MeResponse,
  ApiResponse
} from '~/types'

// Client-only module-level dedupe slot for the in-flight refresh promise.
// Storing a Promise inside useState() leaks it into the SSR payload, which
// devalue cannot serialize (DevalueError "Cannot stringify arbitrary
// non-POJOs"). On the server, refreshes happen per-request anyway and
// don't need cross-component dedupe — so we keep this client-only and
// never touch it during SSR.
let clientRefreshInFlight: Promise<boolean> | null = null

export function useAuth() {
  const config = useRuntimeConfig()
  const router = useRouter()

  // Use different API URL for server (Docker internal) vs client (browser)
  const apiBaseUrl = computed(() =>
    import.meta.server ? config.apiBaseUrlServer : config.public.apiBaseUrl
  )

  // State
  const user = useState<User | null>('auth:user', () => null)
  const permissions = useState<string[]>('auth:permissions', () => [])
  // The short-lived access JWT is memory-only. It may be serialized in the
  // Nuxt payload during SSR, but it is never persisted in a JS-readable
  // cookie. The long-lived refresh JWT is backend-owned and HttpOnly; only
  // its non-secret double-submit CSRF nonce is readable here.
  const accessToken = useState<string | null>('auth:access-token', () => null)
  const csrfToken = useCookie<string | null>('dentalpin_csrf')
  const requestCookie = import.meta.server ? useRequestHeaders(['cookie']).cookie : undefined

  // Computed
  const isAuthenticated = computed(() => !!accessToken.value && !!user.value)

  // Actions
  async function login(credentials: LoginCredentials): Promise<void> {
    // OAuth2PasswordRequestForm expects form data with 'username' field
    const formData = new URLSearchParams()
    formData.append('username', credentials.email)
    formData.append('password', credentials.password)

    const response = await $fetch<AccessTokenResponse>('/api/v1/auth/login', {
      baseURL: apiBaseUrl.value,
      method: 'POST',
      body: formData,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      }
    })

    accessToken.value = response.access_token
    if (import.meta.client) refreshCookie('dentalpin_csrf')

    // Fetch user info after login
    await fetchUser()
  }

  async function logout(): Promise<void> {
    try {
      if (csrfToken.value) {
        await $fetch('/api/v1/auth/logout', {
          baseURL: apiBaseUrl.value,
          method: 'POST',
          credentials: 'include',
          headers: sessionHeaders()
        })
      }
    } catch {
      // Local state must still close if the backend is unavailable.
    }
    clearAuthState()
    if (import.meta.client) refreshCookie('dentalpin_csrf')
    // SSR: skip router.push — calling it from middleware can crash the
    // response. The global auth middleware redirects to /login once it
    // sees isAuthenticated === false.
    if (import.meta.client) {
      await router.push('/login')
    }
  }

  function clearAuthState(): void {
    accessToken.value = null
    user.value = null
    permissions.value = []
  }

  function sessionHeaders(): Record<string, string> {
    const headers: Record<string, string> = {}
    if (csrfToken.value) {
      headers['X-DentalPin-CSRF-Token'] = csrfToken.value
    }
    if (requestCookie) {
      headers.Cookie = requestCookie
    }
    return headers
  }

  // Dedupe concurrent refreshes. Without this, a page that fires N
  // parallel requests on an expired access token triggers N refresh
  // calls — all but one race past the rate limiter and trip 429,
  // which then logs the user out. Sharing one in-flight promise keeps
  // the refresh single-shot per session. Stored in a client-only
  // module-level slot (see top of file) — putting a Promise into
  // useState() breaks SSR payload serialization.
  async function refresh(): Promise<boolean> {
    if (!csrfToken.value) {
      return false
    }

    if (import.meta.client && clientRefreshInFlight) {
      return clientRefreshInFlight
    }

    const run = (async (): Promise<boolean> => {
      try {
        const response = await $fetch<AuthResponse>('/api/v1/auth/refresh', {
          baseURL: apiBaseUrl.value,
          method: 'POST',
          credentials: 'include',
          headers: sessionHeaders()
        })

        accessToken.value = response.access_token
        user.value = response.user

        // /auth/refresh returns user but not the expanded permissions list,
        // so pull /me with the new token. Without this, callers that wake
        // up from an expired access token end up with empty permissions
        // and the sidebar/home strip every permission-gated entry.
        const me = await $fetch<ApiResponse<MeResponse>>('/api/v1/auth/me', {
          baseURL: apiBaseUrl.value,
          headers: { Authorization: `Bearer ${response.access_token}` }
        })
        user.value = me.data.user
        permissions.value = me.data.permissions
        return true
      } catch {
        clearAuthState()
        return false
      }
    })()

    if (import.meta.client) {
      clientRefreshInFlight = run
    }
    try {
      return await run
    } finally {
      if (import.meta.client) {
        clientRefreshInFlight = null
      }
    }
  }

  async function fetchUser(): Promise<void> {
    if (!accessToken.value) {
      return
    }

    try {
      const response = await $fetch<ApiResponse<MeResponse>>('/api/v1/auth/me', {
        baseURL: apiBaseUrl.value,
        headers: {
          Authorization: `Bearer ${accessToken.value}`
        }
      })
      user.value = response.data.user
      permissions.value = response.data.permissions
    } catch (error: unknown) {
      const fetchError = error as { statusCode?: number }
      // Only try refresh on 401 (expired token), not on other errors
      if (fetchError.statusCode === 401) {
        const refreshed = await refresh()
        if (!refreshed) {
          await logout()
        }
      } else {
        // Log the error but don't logout on non-401 errors
        console.error('Failed to fetch user:', error)
        throw error
      }
    }
  }

  // Initialize user if an access token exists, otherwise attempt silent
  // recovery from the backend-owned HttpOnly refresh session.
  // Must never throw: the global auth middleware awaits this on SSR, and
  // an unhandled rejection there crashes the response so the user sees
  // neither the page nor a redirect to /login. On any failure, clear
  // auth state so the middleware can route to /login.
  async function init(): Promise<void> {
    try {
      if (accessToken.value && !user.value) {
        await fetchUser()
      } else if (!accessToken.value) {
        await refresh()
      }
    } catch {
      clearAuthState()
    }
  }

  return {
    user: readonly(user),
    permissions: readonly(permissions),
    accessToken: readonly(accessToken),
    isAuthenticated,
    login,
    logout,
    refresh,
    fetchUser,
    init
  }
}
