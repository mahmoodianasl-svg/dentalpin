<script setup lang="ts">
definePageMeta({ layout: 'guest' })

const voice = usePatientRealtimeVoice()
const patientToken = ref('')
const locale = ref('en')
const consentAccepted = ref(false)
const isBusy = computed(() => ['connecting', 'disconnecting'].includes(voice.status.value))

async function startVoice() {
  if (!consentAccepted.value) return
  await voice.connect({
    patientToken: patientToken.value,
    locale: locale.value || undefined
  })
}
</script>

<template>
  <div class="mx-auto w-full max-w-2xl p-6 space-y-5">
    <div>
      <p class="text-sm text-muted">DentalPin Patient AI</p>
      <h1 class="text-2xl font-semibold">Realtime voice assistant</h1>
      <p class="mt-2 text-sm text-muted">
        This assistant can help with intake, general information and appointment support. It does not diagnose or prescribe.
      </p>
    </div>

    <UCard>
      <div class="space-y-4">
        <UFormField label="Patient session token">
          <UTextarea
            v-model="patientToken"
            :rows="4"
            class="w-full"
            placeholder="Paste a short-lived patient session token"
            :disabled="isBusy || voice.isConnected.value"
          />
        </UFormField>

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
            :disabled="!patientToken.trim() || !consentAccepted || isBusy"
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

        <p v-if="voice.sessionId.value" class="text-xs text-muted break-all">
          Session: {{ voice.sessionId.value }}
        </p>
      </div>
    </UCard>

    <UCard>
      <div class="space-y-2 text-sm text-muted">
        <p class="font-medium text-default">Safety</p>
        <p>For severe pain, uncontrolled bleeding, breathing difficulty, major facial swelling or another emergency, contact local emergency services or your dental clinic directly.</p>
      </div>
    </UCard>
  </div>
</template>
