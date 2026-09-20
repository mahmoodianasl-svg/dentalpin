<script setup lang="ts">
import type { MfaEnrollmentStartResponse, MfaStatusResponse } from '~/types'

const { t } = useI18n()
const auth = useAuth()
const api = useApi()
const status = ref<MfaStatusResponse | null>(null)
const statusLoading = ref(true)
const pending = ref<MfaEnrollmentStartResponse | null>(null)
const recoveryCodes = ref<string[]>([])
const password = ref('')
const confirmationCode = ref('')
const busy = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  try {
    status.value = await api.get<MfaStatusResponse>('/api/v1/auth/mfa/status')
  } catch {
    errorMessage.value = t('auth.mfaUnavailable')
  } finally {
    statusLoading.value = false
  }
})

onUnmounted(() => {
  pending.value = null
  recoveryCodes.value = []
  password.value = ''
  confirmationCode.value = ''
})

async function startEnrollment() {
  if (!password.value || busy.value) return
  errorMessage.value = ''
  busy.value = true
  try {
    pending.value = await auth.beginMfaEnrollment(password.value)
    password.value = ''
  } catch (error: unknown) {
    const code = (error as { statusCode?: number }).statusCode
    errorMessage.value = code === 401 ? t('auth.invalidCredentials') : t('auth.mfaUnavailable')
  } finally {
    busy.value = false
  }
}

async function confirmEnrollment() {
  if (!pending.value || !confirmationCode.value.trim() || busy.value) return
  errorMessage.value = ''
  busy.value = true
  try {
    recoveryCodes.value = await auth.confirmMfaEnrollment(
      pending.value.challenge, confirmationCode.value.trim()
    )
    pending.value = null
    confirmationCode.value = ''
    status.value = { enrolled: true, recovery_codes_remaining: recoveryCodes.value.length }
  } catch (error: unknown) {
    const code = (error as { statusCode?: number }).statusCode
    errorMessage.value = code === 401 ? t('auth.mfaInvalid') : t('auth.mfaUnavailable')
  } finally {
    busy.value = false
  }
}

function dismissRecoveryCodes() {
  recoveryCodes.value = []
}

function restartEnrollment() {
  pending.value = null
  confirmationCode.value = ''
  errorMessage.value = ''
}
</script>

<template>
  <SectionCard
    icon="i-lucide-user"
    :title="t('settings.profile')"
  >
    <div
      v-if="auth.user.value"
      class="space-y-4"
    >
      <div class="flex items-center gap-4">
        <UAvatar
          :alt="auth.user.value.first_name"
          size="lg"
        />
        <div>
          <p class="font-medium text-default">
            {{ auth.user.value.first_name }} {{ auth.user.value.last_name }}
          </p>
          <p class="text-caption text-subtle">
            {{ auth.user.value.email }}
          </p>
        </div>
      </div>
    </div>
  </SectionCard>

  <SectionCard
    icon="i-lucide-shield-check"
    :title="t('auth.mfaSettingsTitle')"
  >
    <div class="space-y-4">
      <p class="text-caption text-muted">
        {{ t('auth.mfaSettingsHint') }}
      </p>
      <p
        v-if="errorMessage"
        role="alert"
        class="text-caption text-error"
      >
        {{ errorMessage }}
      </p>
      <p
        v-if="statusLoading"
        class="text-caption text-muted"
      >
        {{ t('auth.mfaLoading') }}
      </p>

      <template v-else-if="recoveryCodes.length">
        <p class="font-medium text-default">
          {{ t('auth.mfaSaveCodes') }}
        </p>
        <p class="text-caption text-muted">
          {{ t('auth.mfaSaveCodesHint') }}
        </p>
        <ul
          class="grid grid-cols-1 sm:grid-cols-2 gap-2"
          :aria-label="t('auth.mfaSaveCodes')"
        >
          <li
            v-for="code in recoveryCodes"
            :key="code"
            class="font-mono text-sm break-all rounded-token-md p-2 bg-muted"
          >
            {{ code }}
          </li>
        </ul>
        <UButton
          type="button"
          variant="soft"
          @click="dismissRecoveryCodes"
        >
          {{ t('auth.mfaSavedCodes') }}
        </UButton>
      </template>

      <template v-else-if="status?.enrolled">
        <p class="text-caption text-default">
          {{ t('auth.mfaEnabled') }}
        </p>
        <p class="text-caption text-muted">
          {{ t('auth.mfaCodesRemaining', { count: status.recovery_codes_remaining }) }}
        </p>
      </template>

      <form
        v-else-if="status && !pending"
        class="space-y-3"
        @submit.prevent="startEnrollment"
      >
        <UFormField
          :label="t('auth.password')"
          name="enrollmentPassword"
        >
          <UInput
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="w-full"
            :disabled="busy"
          />
        </UFormField>
        <UButton
          type="submit"
          :loading="busy"
          :disabled="busy || !password"
        >
          {{ t('auth.mfaStart') }}
        </UButton>
      </form>

      <form
        v-else
        class="space-y-3"
        @submit.prevent="confirmEnrollment"
      >
        <p class="text-caption text-muted">
          {{ t('auth.mfaSetupHint') }}
        </p>
        <p class="font-mono text-sm break-all rounded-token-md p-2 bg-muted">
          {{ pending?.secret }}
        </p>
        <UFormField
          :label="t('auth.mfaCode')"
          name="enrollmentCode"
        >
          <UInput
            v-model="confirmationCode"
            inputmode="numeric"
            autocomplete="one-time-code"
            class="w-full"
            :disabled="busy"
          />
        </UFormField>
        <div class="flex gap-2">
          <UButton
            type="submit"
            :loading="busy"
            :disabled="busy || !confirmationCode.trim()"
          >
            {{ t('auth.mfaVerify') }}
          </UButton>
          <UButton
            type="button"
            variant="ghost"
            :disabled="busy"
            @click="restartEnrollment"
          >
            {{ t('actions.cancel') }}
          </UButton>
        </div>
      </form>
    </div>
  </SectionCard>
</template>
