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

interface PatientDentalKnowledgeSource {
  entry_id: string
  topic: string
  title: string
  content: string
  source_name: string
  source_reference: string
  locale: string
}

interface PatientDentalKnowledgeSearchResponse {
  sources: PatientDentalKnowledgeSource[]
  fallback_required: boolean
  patient_education_only: boolean
}

interface RealtimeFunctionCallDone {
  type: 'response.function_call_arguments.done'
  call_id: string
  name: string
  arguments: string
}

interface ConnectPatientVoiceOptions {
  patientToken: string
  locale?: string
}

const OPENAI_REALTIME_CALLS_URL = 'https://api.openai.com/v1/realtime/calls'
const PATIENT_KNOWLEDGE_TOOL = 'search_patient_dental_knowledge'
const PATIENT_HANDOFF_TOOL = 'request_patient_human_handoff'
const HANDOFF_URGENCIES = new Set(['routine', 'soon', 'urgent', 'emergency_escalation'])

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
  let activePatientToken: string | null = null
  let activeLocale = 'en'

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

    activePatientToken = null
    activeLocale = 'en'
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

  async function searchPatientKnowledge(query: string, topic?: string | null) {
    if (!activePatientToken) {
      throw new Error('Patient session is not authenticated')
    }

    return await $fetch<ApiEnvelope<PatientDentalKnowledgeSearchResponse>>(
      '/api/v1/patient_agent/patient/knowledge/search',
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: {
          Authorization: `Bearer ${activePatientToken}`
        },
        body: {
          query,
          locale: activeLocale,
          topic: topic || null,
          limit: 5
        }
      }
    )
  }

  async function requestPatientHandoff(reason: string, urgency: string) {
    if (!activePatientToken || !sessionId.value) {
      throw new Error('Patient session is not authenticated')
    }

    return await $fetch<ApiEnvelope<{ session_id: string, handoff_state: string }>>(
      `/api/v1/patient_agent/patient/sessions/${sessionId.value}/handoff`,
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: {
          Authorization: `Bearer ${activePatientToken}`
        },
        body: { reason, urgency }
      }
    )
  }

  function sendRealtimeEvent(event: Record<string, unknown>) {
    if (!dataChannel || dataChannel.readyState !== 'open') {
      throw new Error('Realtime event channel is not open')
    }
    dataChannel.send(JSON.stringify(event))
  }

  async function handleKnowledgeCall(event: RealtimeFunctionCallDone) {
    let args: { query?: unknown, topic?: unknown }
    try {
      args = JSON.parse(event.arguments) as { query?: unknown, topic?: unknown }
    } catch {
      args = {}
    }

    const query = typeof args.query === 'string' ? args.query.trim() : ''
    const topic = typeof args.topic === 'string' ? args.topic : null

    let output: PatientDentalKnowledgeSearchResponse | { fallback_required: true, error: string }
    if (query.length < 2) {
      output = {
        fallback_required: true,
        error: 'A valid dental education query is required.'
      }
    } else {
      try {
        const response = await searchPatientKnowledge(query, topic)
        output = response.data
      } catch {
        output = {
          fallback_required: true,
          error: 'Approved clinic knowledge could not be retrieved.'
        }
      }
    }

    sendRealtimeEvent({
      type: 'conversation.item.create',
      item: {
        type: 'function_call_output',
        call_id: event.call_id,
        output: JSON.stringify(output)
      }
    })
    sendRealtimeEvent({ type: 'response.create' })
  }

  async function handleHandoffCall(event: RealtimeFunctionCallDone) {
    let args: { reason?: unknown, urgency?: unknown }
    try {
      args = JSON.parse(event.arguments) as { reason?: unknown, urgency?: unknown }
    } catch {
      args = {}
    }

    const reason = typeof args.reason === 'string' ? args.reason.trim() : ''
    const urgency = typeof args.urgency === 'string' ? args.urgency : 'routine'

    let output: { requested: boolean, handoff_state?: string, error?: string }
    if (!reason || !HANDOFF_URGENCIES.has(urgency)) {
      output = { requested: false, error: 'A factual handoff summary and valid urgency are required.' }
    } else {
      try {
        const response = await requestPatientHandoff(reason, urgency)
        output = { requested: true, handoff_state: response.data.handoff_state }
      } catch {
        output = { requested: false, error: 'Human handoff could not be requested.' }
      }
    }

    sendRealtimeEvent({
      type: 'conversation.item.create',
      item: {
        type: 'function_call_output',
        call_id: event.call_id,
        output: JSON.stringify(output)
      }
    })
    sendRealtimeEvent({ type: 'response.create' })
  }

  async function handleFunctionCall(event: RealtimeFunctionCallDone) {
    if (event.name === PATIENT_KNOWLEDGE_TOOL) {
      await handleKnowledgeCall(event)
    } else if (event.name === PATIENT_HANDOFF_TOOL) {
      await handleHandoffCall(event)
    }
  }

  async function handleRealtimeMessage(message: MessageEvent<string>) {
    let event: unknown
    try {
      event = JSON.parse(message.data)
    } catch {
      return
    }

    if (
      typeof event === 'object'
      && event !== null
      && 'type' in event
      && event.type === 'response.function_call_arguments.done'
    ) {
      await handleFunctionCall(event as RealtimeFunctionCallDone)
    }
  }

  async function exchangeSdp(clientSecret: string, offer: RTCSessionDescriptionInit) {
    const response = await fetch(OPENAI_REALTIME_CALLS_URL, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${clientSecret}`,
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
    if (typeof window === 'undefined') {
      throw new Error('Realtime voice requires a browser')
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Microphone access is not supported by this browser')
    }

    status.value = 'connecting'
    errorMessage.value = null

    try {
      activePatientToken = options.patientToken
      activeLocale = options.locale || 'en'
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
      dataChannel.onmessage = (event) => {
        void handleRealtimeMessage(event)
      }
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
