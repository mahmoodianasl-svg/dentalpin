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

interface RealtimeSessionEnded {
  session_id: string
  status: 'ended'
  ended_at: string
}

interface VisualSnapshotConsentRevoked {
  session_id: string
  consent_type: 'video'
  granted: false
  scope: 'visual_snapshot_only'
  continuous_video: false
}

interface VisualSnapshotAuthorization {
  snapshot_id: string
  authorized: boolean
  scope: 'visual_snapshot_only'
  media_content_persisted: boolean
  continuous_video: boolean
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

interface IntakeRiskAssessmentResponse {
  session_id: string
  urgency: 'routine' | 'soon' | 'urgent' | 'emergency_escalation'
  must_handoff: boolean
  handoff_state: string | null
  diagnostic: false
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
  visualSnapshotConsent?: boolean
}

const OPENAI_REALTIME_CALLS_URL = 'https://api.openai.com/v1/realtime/calls'
const PATIENT_KNOWLEDGE_TOOL = 'search_patient_dental_knowledge'
const PATIENT_INTAKE_RISK_TOOL = 'assess_patient_intake_risk'
const PATIENT_HANDOFF_TOOL = 'request_patient_human_handoff'
const INTAKE_SIGNALS = new Set([
  'pain',
  'swelling',
  'bleeding',
  'fever_or_systemic_illness',
  'trauma',
  'difficulty_breathing',
  'difficulty_swallowing',
  'uncontrolled_bleeding',
  'facial_or_neck_swelling'
])
const VISUAL_SNAPSHOT_TYPES = new Set(['image/jpeg', 'image/png'])
const MAX_VISUAL_SNAPSHOT_BYTES = 5 * 1024 * 1024

export function usePatientRealtimeVoice() {
  const config = useRuntimeConfig()
  const status = ref<PatientVoiceStatus>('idle')
  const sessionId = ref<string | null>(null)
  const errorMessage = ref<string | null>(null)
  const isMuted = ref(false)
  const visualSnapshotConsentEnabled = ref(false)
  const isRevokingVisualSnapshotConsent = ref(false)

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
    visualSnapshotConsentEnabled.value = false
    isRevokingVisualSnapshotConsent.value = false
  }

  async function mintSession(
    patientToken: string,
    locale?: string,
    visualSnapshotConsent = false
  ) {
    return await $fetch<ApiEnvelope<RealtimeSessionCreated>>(
      '/api/v1/patient_agent/patient/sessions',
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: { Authorization: `Bearer ${patientToken}` },
        body: {
          channel: 'voice',
          locale: locale || null,
          ai_consent: true,
          audio_consent: true,
          video_consent: visualSnapshotConsent
        }
      }
    )
  }

  async function endPatientSession() {
    if (!activePatientToken || !sessionId.value) return
    await $fetch<ApiEnvelope<RealtimeSessionEnded>>(
      `/api/v1/patient_agent/patient/sessions/${sessionId.value}/end`,
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: { Authorization: `Bearer ${activePatientToken}` }
      }
    )
  }

  async function searchPatientKnowledge(query: string, topic?: string | null) {
    if (!activePatientToken) throw new Error('Patient session is not authenticated')
    return await $fetch<ApiEnvelope<PatientDentalKnowledgeSearchResponse>>(
      '/api/v1/patient_agent/patient/knowledge/search',
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: { Authorization: `Bearer ${activePatientToken}` },
        body: { query, locale: activeLocale, topic: topic || null, limit: 5 }
      }
    )
  }

  async function assessPatientIntakeRisk(reason: string, signals: string[]) {
    if (!activePatientToken || !sessionId.value) {
      throw new Error('Patient session is not authenticated')
    }
    return await $fetch<ApiEnvelope<IntakeRiskAssessmentResponse>>(
      `/api/v1/patient_agent/patient/sessions/${sessionId.value}/intake-risk/assess`,
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: { Authorization: `Bearer ${activePatientToken}` },
        body: { reason, signals }
      }
    )
  }

  async function requestPatientHandoff(reason: string) {
    if (!activePatientToken || !sessionId.value) {
      throw new Error('Patient session is not authenticated')
    }
    return await $fetch<ApiEnvelope<{ session_id: string, handoff_state: string }>>(
      `/api/v1/patient_agent/patient/sessions/${sessionId.value}/handoff`,
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: { Authorization: `Bearer ${activePatientToken}` },
        body: { reason }
      }
    )
  }

  async function authorizeVisualSnapshot(file: File) {
    if (!activePatientToken || !sessionId.value) {
      throw new Error('Patient session is not authenticated')
    }
    return await $fetch<ApiEnvelope<VisualSnapshotAuthorization>>(
      `/api/v1/patient_agent/patient/sessions/${sessionId.value}/visual-snapshots/authorize`,
      {
        baseURL: apiBaseUrl.value,
        method: 'POST',
        headers: { Authorization: `Bearer ${activePatientToken}` },
        body: { mime_type: file.type, size_bytes: file.size }
      }
    )
  }

  async function stopVisualSnapshotSharing() {
    errorMessage.value = null
    if (!isConnected.value || !activePatientToken || !sessionId.value) {
      const error = new Error('Start the realtime voice session before changing image sharing')
      errorMessage.value = error.message
      throw error
    }
    if (!visualSnapshotConsentEnabled.value) return
    if (isRevokingVisualSnapshotConsent.value) {
      const error = new Error('Visual snapshot consent revocation is already in progress')
      errorMessage.value = error.message
      throw error
    }

    isRevokingVisualSnapshotConsent.value = true
    try {
      const response = await $fetch<ApiEnvelope<VisualSnapshotConsentRevoked>>(
        `/api/v1/patient_agent/patient/sessions/${sessionId.value}/visual-snapshot-consent/revoke`,
        {
          baseURL: apiBaseUrl.value,
          method: 'POST',
          headers: { Authorization: `Bearer ${activePatientToken}` }
        }
      )
      if (response.data.granted !== false || response.data.consent_type !== 'video') {
        throw new Error('Visual snapshot consent revocation was not confirmed')
      }
      visualSnapshotConsentEnabled.value = false
    } catch (error: unknown) {
      errorMessage.value = error instanceof Error
        ? error.message
        : 'Unable to stop visual snapshot sharing'
      throw error
    } finally {
      isRevokingVisualSnapshotConsent.value = false
    }
  }

  function sendRealtimeEvent(event: Record<string, unknown>) {
    if (!dataChannel || dataChannel.readyState !== 'open') {
      throw new Error('Realtime event channel is not open')
    }
    dataChannel.send(JSON.stringify(event))
  }

  function readImageAsDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onerror = () => reject(new Error('Unable to read visual snapshot'))
      reader.onload = () => {
        if (typeof reader.result !== 'string') {
          reject(new Error('Unable to read visual snapshot'))
          return
        }
        resolve(reader.result)
      }
      reader.readAsDataURL(file)
    })
  }

  function ensureVisualSnapshotSharingActive() {
    if (isRevokingVisualSnapshotConsent.value) {
      throw new Error('Visual snapshot sharing is stopping for this session')
    }
    if (!visualSnapshotConsentEnabled.value) {
      throw new Error('Visual snapshot consent was not granted for this session')
    }
  }

  async function sendVisualSnapshot(file: File) {
    errorMessage.value = null
    try {
      if (!isConnected.value) throw new Error('Start the realtime voice session before sharing an image')
      ensureVisualSnapshotSharingActive()
      if (!VISUAL_SNAPSHOT_TYPES.has(file.type)) throw new Error('Visual snapshots must be PNG or JPEG images')
      if (file.size <= 0 || file.size > MAX_VISUAL_SNAPSHOT_BYTES) {
        throw new Error('Visual snapshot must be between 1 byte and 5 MB')
      }
      const authorization = await authorizeVisualSnapshot(file)
      if (!authorization.data.authorized) throw new Error('Visual snapshot sharing was not authorized')
      ensureVisualSnapshotSharingActive()
      const imageUrl = await readImageAsDataUrl(file)
      ensureVisualSnapshotSharingActive()
      sendRealtimeEvent({
        type: 'conversation.item.create',
        item: {
          type: 'message',
          role: 'user',
          content: [
            { type: 'input_image', image_url: imageUrl, detail: 'auto' },
            {
              type: 'input_text',
              text: 'This patient-selected image is visual context for intake and education only. Do not diagnose, prescribe, approve treatment, or write clinical records from the image. Escalate clinical decisions or concerning findings to a qualified dental professional.'
            }
          ]
        }
      })
      sendRealtimeEvent({ type: 'response.create' })
    } catch (error: unknown) {
      errorMessage.value = error instanceof Error ? error.message : 'Unable to share visual snapshot'
      throw error
    }
  }

  function sendFunctionOutput(callId: string, output: unknown) {
    sendRealtimeEvent({
      type: 'conversation.item.create',
      item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(output) }
    })
    sendRealtimeEvent({ type: 'response.create' })
  }

  async function handleKnowledgeCall(event: RealtimeFunctionCallDone) {
    let args: { query?: unknown, topic?: unknown }
    try { args = JSON.parse(event.arguments) as { query?: unknown, topic?: unknown } } catch { args = {} }
    const query = typeof args.query === 'string' ? args.query.trim() : ''
    const topic = typeof args.topic === 'string' ? args.topic : null
    let output: PatientDentalKnowledgeSearchResponse | { fallback_required: true, error: string }
    if (query.length < 2) {
      output = { fallback_required: true, error: 'A valid dental education query is required.' }
    } else {
      try { output = (await searchPatientKnowledge(query, topic)).data } catch {
        output = { fallback_required: true, error: 'Approved clinic knowledge could not be retrieved.' }
      }
    }
    sendFunctionOutput(event.call_id, output)
  }

  async function handleIntakeRiskCall(event: RealtimeFunctionCallDone) {
    let args: { reason?: unknown, signals?: unknown }
    try { args = JSON.parse(event.arguments) as { reason?: unknown, signals?: unknown } } catch { args = {} }
    const reason = typeof args.reason === 'string' ? args.reason.trim() : ''
    const signals = Array.isArray(args.signals)
      ? args.signals.filter((value): value is string => typeof value === 'string' && INTAKE_SIGNALS.has(value))
      : []
    if (!reason || signals.length === 0) {
      sendFunctionOutput(event.call_id, { assessed: false, error: 'A factual summary and valid intake signals are required.' })
      return
    }
    try {
      sendFunctionOutput(event.call_id, (await assessPatientIntakeRisk(reason, signals)).data)
    } catch {
      sendFunctionOutput(event.call_id, { assessed: false, error: 'Intake risk could not be assessed.' })
    }
  }

  async function handleHandoffCall(event: RealtimeFunctionCallDone) {
    let args: { reason?: unknown }
    try { args = JSON.parse(event.arguments) as { reason?: unknown } } catch { args = {} }
    const reason = typeof args.reason === 'string' ? args.reason.trim() : ''
    if (!reason) {
      sendFunctionOutput(event.call_id, { requested: false, error: 'A factual handoff summary is required.' })
      return
    }
    try {
      const response = await requestPatientHandoff(reason)
      sendFunctionOutput(event.call_id, { requested: true, handoff_state: response.data.handoff_state })
    } catch {
      sendFunctionOutput(event.call_id, { requested: false, error: 'Human handoff could not be requested.' })
    }
  }

  async function handleFunctionCall(event: RealtimeFunctionCallDone) {
    if (event.name === PATIENT_KNOWLEDGE_TOOL) await handleKnowledgeCall(event)
    else if (event.name === PATIENT_INTAKE_RISK_TOOL) await handleIntakeRiskCall(event)
    else if (event.name === PATIENT_HANDOFF_TOOL) await handleHandoffCall(event)
  }

  async function handleRealtimeMessage(message: MessageEvent<string>) {
    let event: unknown
    try { event = JSON.parse(message.data) } catch { return }
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
    if (!response.ok) throw new Error(`Realtime SDP exchange failed (${response.status})`)
    return await response.text()
  }

  async function connect(options: ConnectPatientVoiceOptions) {
    if (status.value === 'connecting' || status.value === 'connected') return
    if (!options.patientToken.trim()) throw new Error('Patient session token is required')
    if (typeof window === 'undefined') throw new Error('Realtime voice requires a browser')
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access is not supported by this browser')

    status.value = 'connecting'
    errorMessage.value = null
    try {
      activePatientToken = options.patientToken
      activeLocale = options.locale || 'en'
      visualSnapshotConsentEnabled.value = options.visualSnapshotConsent === true
      const descriptor = (await mintSession(options.patientToken, options.locale, visualSnapshotConsentEnabled.value)).data
      if (!descriptor.client_secret) throw new Error('Realtime provider did not return a client secret')
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
        if (peerConnection.connectionState === 'connected') status.value = 'connected'
        else if (['failed', 'disconnected', 'closed'].includes(peerConnection.connectionState)) {
          if (status.value !== 'disconnecting') {
            status.value = peerConnection.connectionState === 'failed' ? 'error' : 'idle'
          }
        }
      }
      dataChannel = peerConnection.createDataChannel('oai-events')
      dataChannel.onmessage = (event) => { void handleRealtimeMessage(event) }
      dataChannel.onerror = () => { errorMessage.value = 'Realtime event channel failed' }
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false
      })
      for (const track of localStream.getAudioTracks()) peerConnection.addTrack(track, localStream)
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
    localStream?.getAudioTracks().forEach((track) => { track.enabled = !muted })
  }

  function toggleMute() { setMuted(!isMuted.value) }

  async function disconnect() {
    if (status.value === 'idle') return
    status.value = 'disconnecting'
    errorMessage.value = null
    try { await endPatientSession() } catch (error: unknown) {
      errorMessage.value = error instanceof Error ? error.message : 'Unable to end realtime session cleanly'
    } finally {
      cleanupMedia()
      sessionId.value = null
      status.value = 'idle'
    }
  }

  onBeforeUnmount(() => { cleanupMedia() })

  return {
    status: readonly(status),
    sessionId: readonly(sessionId),
    errorMessage: readonly(errorMessage),
    isMuted: readonly(isMuted),
    visualSnapshotConsentEnabled: readonly(visualSnapshotConsentEnabled),
    isRevokingVisualSnapshotConsent: readonly(isRevokingVisualSnapshotConsent),
    isConnected,
    connect,
    disconnect,
    sendVisualSnapshot,
    stopVisualSnapshotSharing,
    setMuted,
    toggleMute
  }
}
