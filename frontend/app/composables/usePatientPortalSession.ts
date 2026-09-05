interface ApiEnvelope<T> {
  data: T
}

interface PatientPortalLoginResponse {
  patient_token: string
  token_type: 'bearer'
  expires_in_seconds: number
  patient_id: string
  clinic_id: string
}

interface PatientPortalLoginInput {
  clinicId: string
  email: string
  password: string
}

interface StoredPatientPortalSession {
  patientToken: string
  patientId: string
  clinicId: string
  expiresAt: number
}

const STORAGE_KEY = 'dentalpin.patientPortalSession'

export function usePatientPortalSession() {
  const config = useRuntimeConfig()
  const patientToken = useState<string | null>('patient-portal-token', () => null)
  const patientId = useState<string | null>('patient-portal-patient-id', () => null)
  const clinicId = useState<string | null>('patient-portal-clinic-id', () => null)
  const expiresAt = useState<number | null>('patient-portal-expires-at', () => null)
  const errorMessage = ref<string | null>(null)
  const isAuthenticating = ref(false)

  const apiBaseUrl = computed(() => config.public.apiBaseUrl)
  const isAuthenticated = computed(() => Boolean(
    patientToken.value
      && expiresAt.value
      && expiresAt.value > Date.now()
  ))

  function persist() {
    if (typeof window === 'undefined' || !patientToken.value || !patientId.value || !clinicId.value || !expiresAt.value) return
    const stored: StoredPatientPortalSession = {
      patientToken: patientToken.value,
      patientId: patientId.value,
      clinicId: clinicId.value,
      expiresAt: expiresAt.value
    }
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stored))
  }

  function clear() {
    patientToken.value = null
    patientId.value = null
    clinicId.value = null
    expiresAt.value = null
    errorMessage.value = null
    if (typeof window !== 'undefined') window.sessionStorage.removeItem(STORAGE_KEY)
  }

  function restore() {
    if (typeof window === 'undefined' || patientToken.value) return
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return
    try {
      const stored = JSON.parse(raw) as StoredPatientPortalSession
      if (!stored.patientToken || !stored.patientId || !stored.clinicId || stored.expiresAt <= Date.now()) {
        clear()
        return
      }
      patientToken.value = stored.patientToken
      patientId.value = stored.patientId
      clinicId.value = stored.clinicId
      expiresAt.value = stored.expiresAt
    } catch {
      clear()
    }
  }

  async function login(input: PatientPortalLoginInput) {
    isAuthenticating.value = true
    errorMessage.value = null
    try {
      const response = await $fetch<ApiEnvelope<PatientPortalLoginResponse>>(
        '/api/v1/patient_agent/portal/login',
        {
          baseURL: apiBaseUrl.value,
          method: 'POST',
          body: {
            clinic_id: input.clinicId.trim(),
            email: input.email.trim(),
            password: input.password
          }
        }
      )
      patientToken.value = response.data.patient_token
      patientId.value = response.data.patient_id
      clinicId.value = response.data.clinic_id
      expiresAt.value = Date.now() + response.data.expires_in_seconds * 1000
      persist()
    } catch (error: unknown) {
      clear()
      errorMessage.value = 'Unable to sign in. Check your clinic, email and password.'
      throw error
    } finally {
      isAuthenticating.value = false
    }
  }

  restore()

  return {
    patientToken: readonly(patientToken),
    patientId: readonly(patientId),
    clinicId: readonly(clinicId),
    expiresAt: readonly(expiresAt),
    errorMessage: readonly(errorMessage),
    isAuthenticating: readonly(isAuthenticating),
    isAuthenticated,
    login,
    logout: clear,
    restore
  }
}
