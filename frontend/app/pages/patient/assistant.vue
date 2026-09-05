<script setup lang="ts">
definePageMeta({ layout: 'guest' })

const portal = usePatientPortalSession()
const voice = usePatientRealtimeVoice()
const clinicIdInput = ref(portal.clinicId.value || '')
const email = ref('')
const password = ref('')
const locale = ref('en')
const consentAccepted = ref(false)
const isBusy = computed(() => ['connecting', 'disconnecting'].includes(voice.status.value))

async function signIn() {
  await portal.login({
    clinicId: clinicIdInput.value,
    email: email.value,
    password: password.value
  })
  password.value = ''
}

async function startVoice() {
  if (!consentAccepted.value || !portal.patientToken.value) return
  await voice.connect({
    patientToken: portal.patientToken.value,
    locale: locale.value || undefined
  })
}

async function signOut() {
  if (voice.isConnected.value) await voice.disconnect()
  portal.logout()
  consentAccepted.value = false
}
</script>

<template>
  <div class="mx-auto w-full max-w-2xl p-6 space-y-5">
    <div>
      <p class="text-sm text-muted">
        DentalPin Patient AI
      </p>
      <h1 class="text-2xl font-semibold">
        Realtime voice assistant
      </h1>
      <p class="mt-2 text-sm text-muted">
        This assistant can help with intake, general information and appointment support. It does not diagnose or prescribe.
      </p>
    </div>

    <UCard v-if="!portal.isAuthenticated.value">
      <div class="space-y-4">
        <div>
          <p class="font-medium text-default">
            Patient portal sign in
          </p>
          <p class="mt-1 text-sm text-muted">
            Sign in with the patient portal account provided by your dental clinic.
          </p>
        </div>

        <UFormField label="Clinic ID">
          <UInput
            v-model="clinicIdInput"
            class="w-full"
            autocomplete="organization"
            placeholder="Clinic identifier"
            :disabled="portal.isAuthenticating.value"
          />
        </UFormField>

        <UFormField label="Email">
          <UInput
            v-model="email"
            type="email"
            class="w-full"
            autocomplete="email"
            placeholder="patient@example.com"
            :disabled="portal.isAuthenticating.value"
          />
        </UFormField>

        <UFormField label="Password">
          <UInput
            v-model="password"
            type="password"
            class="w-full"
            autocomplete="current-password"
            :disabled="portal.isAuthenticating.value"
          />
        </UFormField>

        <div
          v-if="portal.errorMessage.value"
          class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          role="alert"
        >
          {{ portal.errorMessage.value }}
        </div>

        <UButton
          icon="i-lucide-log-in"
          :loading="portal.isAuthenticating.value"
          :disabled="!clinicIdInput.trim() || !email.trim() || password.length < 8"
          @click="signIn"
        >
          Sign in
        </UButton>
      </div>
    </UCard>

    <UCard v-else>
      <div class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="font-medium text-default">
              Patient portal connected
            </p>
            <p class="text-xs text-muted">
              Authenticated patient session
            </p>
          </div>
          <UButton
            icon="i-lucide-log-out"
            variant="soft"
            :disabled="isBusy"
            @click="signOut"
          >
            Sign out
          </UButton>
        </div>

        <UFormField label="Language / locale">
          <UInput
            v-model="locale"
            class="w-full"
            placeholder="en, tr, de..."
            :disabled="isBusy || voice.isConnected.value"
          />
        </UFormField>

        <UCheckbox
          v-model="consentAccepted"
          label="I consent to this AI voice session and microphone audio processing. Recording is not enabled by default."
          :disabled="isBusy || voice.isConnected.value"
        />

        <div
          v-if="voice.errorMessage.value"
          class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          role="alert"
        >
          {{ voice.errorMessage.value }}
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <UButton
            v-if="!voice.isConnected.value"
            icon="i-lucide-mic"
            :loading="voice.status.value === 'connecting'"
            :disabled="!portal.isAuthenticated.value || !consentAccepted || isBusy"
            @click="startVoice"
          >
            Start voice session
          </UButton>

          <template v-else>
            <UButton
              :icon="voice.isMuted.value ? 'i-lucide-mic-off' : 'i-lucide-mic'"
              variant="soft"
              @click="voice.toggleMute"
            >
              {{ voice.isMuted.value ? 'Unmute' : 'Mute' }}
            </UButton>

            <UButton
              icon="i-lucide-phone-off"
              color="error"
              variant="soft"
              @click="voice.disconnect"
            >
              End session
            </UButton>
          </template>

          <span class="text-sm text-muted">
            Status: {{ voice.status.value }}
          </span>
        </div>

        <p
          v-if="voice.sessionId.value"
          class="text-xs text-muted break-all"
        >
          Session: {{ voice.sessionId.value }}
        </p>
      </div>
    </UCard>

    <UCard>
      <div class="space-y-2 text-sm text-muted">
        <p class="font-medium text-default">
          Safety
        </p>
        <p>
          For severe pain, uncontrolled bleeding, breathing difficulty, major facial swelling or another emergency, contact local emergency services or your dental clinic directly.
        </p>
      </div>
    </UCard>
  </div>
</template>
