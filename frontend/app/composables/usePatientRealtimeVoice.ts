type PatientVoiceStatus = 'idle' | 'connecting' | 'connected' | 'disconnecting' | 'error'

interface ApiEnvelope<T> {
  data: T
}

interface RealtimeSessionCreated {
  session_id: string
  channel: 'voice'
  provider: string
  client_secret: string | null
  expires_at_epoch: number | null
}

interface ConnectPatientVoiceOptions {
  patientToken: string
  locale?: string
}

const OPENAI_REALTIME_CALLS_URL = 'https://api.openai.com/v1/realtime/calls'

export function usePatientRealtimeVoice() {
  const config = useRuntimeConfig()
  const status = ref<PatientVoiceStatus>('idle')
  const sessionId = ref<string | null>(null)
  const errorMessage = ref<string | null>(null)
  const isMuted = ref(false)

  let peerConnection: RTCPeerConnection | null = null
  let localStream: MediaStream | null = null
  let remoteAudio: HTMLAudioElement | null = null
  let dataChannel: RTCDataChannel | null = null

  const apiBaseUrl = computed(() => config.public.apiBaseUrl)
  const isConnected = computed(() => status.value === 'connected')

  function cleanupMedia() {
    dataChannel?.close()
    dataChannel = null

    peerConnection?.close()
    peerConnection = null

    localStream?.getTracks().forEach(track => track.stop())
    localStream = null

    if (remoteAudio) {
      remoteAudio.srcObject = null
      remoteAudio.remove()
      remoteAudio = null
    }

    isMuted.value = false
  }

  async function mintSession(patientToken: string, locale?: string) {
    return await $fetch<ApiEnvelope<RealtimeSessionCreated>>(
      '/api/v1/patient_agent/patient/sessions',
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: {
          Authorization: `Bearer ${patientToken}`
        },
        body: {
          channel: 'voice',
          locale: locale || null,
          ai_consent: true,
          audio_consent: true,
          video_consent: false
        }
      }
    )
  }

  async function exchangeSdp(clientSecret: string, offer: RTCSessionDescriptionInit) {
    const response = await fetch(OPENAI_REALTIME_CALLS_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${clientSecret}`,
        'Content-Type': 'application/sdp'
      },
      body: offer.sdp
    })

    if (!response.ok) {
      throw new Error(`Realtime SDP exchange failed (${response.status})`)
    }

    return await response.text()
  }

  async function connect(options: ConnectPatientVoiceOptions) {
    if (status.value === 'connecting' || status.value === 'connected') return
    if (!options.patientToken.trim()) {
      throw new Error('Patient session token is required')
    }
    if (!import.meta.client) {
      throw new Error('Realtime voice requires a browser')
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Microphone access is not supported by this browser')
    }

    status.value = 'connecting'
    errorMessage.value = null

    try {
      const minted = await mintSession(options.patientToken, options.locale)
      const descriptor = minted.data
      if (!descriptor.client_secret) {
        throw new Error('Realtime provider did not return a client secret')
      }

      sessionId.value = descriptor.session_id
      peerConnection = new RTCPeerConnection()

      remoteAudio = document.createElement('audio')
      remoteAudio.autoplay = true
      remoteAudio.setAttribute('aria-hidden', 'true')
      document.body.appendChild(remoteAudio)

      peerConnection.ontrack = (event) => {
        const [stream] = event.streams
        if (stream && remoteAudio) remoteAudio.srcObject = stream
      }

      peerConnection.onconnectionstatechange = () => {
        if (!peerConnection) return
        if (peerConnection.connectionState === 'connected') {
          status.value = 'connected'
        } else if (['failed', 'disconnected', 'closed'].includes(peerConnection.connectionState)) {
          if (status.value !== 'disconnecting') {
            status.value = peerConnection.connectionState === 'failed' ? 'error' : 'idle'
          }
        }
      }

      dataChannel = peerConnection.createDataChannel('oai-events')
      dataChannel.onerror = () => {
        errorMessage.value = 'Realtime event channel failed'
      }

      localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        },
        video: false
      })

      for (const track of localStream.getAudioTracks()) {
        peerConnection.addTrack(track, localStream)
      }

      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)
      const answerSdp = await exchangeSdp(descriptor.client_secret, offer)
      await peerConnection.setRemoteDescription({ type: 'answer', sdp: answerSdp })
    } catch (error: unknown) {
      cleanupMedia()
      sessionId.value = null
      status.value = 'error'
      errorMessage.value = error instanceof Error ? error.message : 'Unable to start realtime voice'
      throw error
    }
  }

  function setMuted(muted: boolean) {
    isMuted.value = muted
    localStream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted
    })
  }

  function toggleMute() {
    setMuted(!isMuted.value)
  }

  async function disconnect() {
    if (status.value === 'idle') return
    status.value = 'disconnecting'
    cleanupMedia()
    sessionId.value = null
    status.value = 'idle'
  }

  onBeforeUnmount(() => {
    cleanupMedia()
  })

  return {
    status: readonly(status),
    sessionId: readonly(sessionId),
    errorMessage: readonly(errorMessage),
    isMuted: readonly(isMuted),
    isConnected,
    connect,
    disconnect,
    setMuted,
    toggleMute
  }
}
