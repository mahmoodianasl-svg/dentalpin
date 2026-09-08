import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { usePatientRealtimeVoice } from '../../app/composables/usePatientRealtimeVoice'

vi.stubGlobal('useRuntimeConfig', () => ({
  public: { apiBaseUrl: 'http://localhost:8000' }
}))
vi.stubGlobal('onBeforeUnmount', vi.fn())
vi.stubGlobal('readonly', (value: unknown) => value)
vi.stubGlobal('computed', (getter: () => unknown) => ({
  get value() {
    return getter()
  }
}))
vi.stubGlobal('ref', ref)
vi.stubGlobal('window', {})

const fetchMock = vi.fn()
vi.stubGlobal('$fetch', fetchMock)

const dataChannel = {
  close: vi.fn(),
  onerror: null as (() => void) | null,
  onmessage: null as ((event: MessageEvent<string>) => void) | null,
  readyState: 'open',
  send: vi.fn()
}

class MockPeerConnection {
  connectionState = 'new'
  localDescription: RTCSessionDescriptionInit | null = null
  ontrack: ((event: RTCTrackEvent) => void) | null = null
  onconnectionstatechange: (() => void) | null = null
  addTrack = vi.fn()
  createDataChannel = vi.fn(() => dataChannel)
  createOffer = vi.fn(async () => ({ type: 'offer', sdp: 'offer-sdp' }))

  setLocalDescription = vi.fn(async (description) => {
    this.localDescription = description
  })

  setRemoteDescription = vi.fn(async () => {
    this.connectionState = 'connected'
    this.onconnectionstatechange?.()
  })

  close = vi.fn()
}

vi.stubGlobal('RTCPeerConnection', MockPeerConnection)

class MockFileReader {
  result: string | ArrayBuffer | null = null
  onerror: (() => void) | null = null
  onload: (() => void) | null = null

  readAsDataURL(file: File) {
    this.result = `data:${file.type};base64,dGVzdC1pbWFnZQ==`
    this.onload?.()
  }
}

vi.stubGlobal('FileReader', MockFileReader)

const track = { stop: vi.fn(), enabled: true }
const stream = {
  getTracks: () => [track],
  getAudioTracks: () => [track]
}

Object.defineProperty(globalThis, 'navigator', {
  value: {
    mediaDevices: {
      getUserMedia: vi.fn(async () => stream)
    }
  },
  configurable: true
})

vi.stubGlobal('document', {
  body: { appendChild: vi.fn() },
  createElement: vi.fn(() => ({
    autoplay: false,
    srcObject: null,
    setAttribute: vi.fn(),
    remove: vi.fn()
  }))
})

const nativeFetch = vi.fn(async () => ({
  ok: true,
  status: 200,
  text: async () => 'answer-sdp'
}))
vi.stubGlobal('fetch', nativeFetch)

function mintedSession() {
  return {
    data: {
      session_id: 'session-1',
      channel: 'voice',
      provider: 'openai',
      client_secret: 'ephemeral-secret',
      expires_at_epoch: 123
    }
  }
}

function mockMintSession() {
  fetchMock.mockResolvedValue(mintedSession())
}

function visualAuthorization() {
  return {
    data: {
      snapshot_id: 'snapshot-1',
      authorized: true,
      scope: 'visual_snapshot_only',
      media_content_persisted: false,
      continuous_video: false
    }
  }
}

describe('usePatientRealtimeVoice', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    nativeFetch.mockClear()
    dataChannel.send.mockReset()
    dataChannel.close.mockReset()
    dataChannel.onerror = null
    dataChannel.onmessage = null
    track.enabled = true
  })

  it('mints a voice session with AI/audio consent and no visual snapshot consent by default', async () => {
    mockMintSession()

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token', locale: 'tr' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/patient_agent/patient/sessions',
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer patient-token' },
        body: expect.objectContaining({
          channel: 'voice',
          locale: 'tr',
          ai_consent: true,
          audio_consent: true,
          video_consent: false
        })
      })
    )
    expect(voice.visualSnapshotConsentEnabled.value).toBe(false)
    expect(nativeFetch).toHaveBeenCalledWith(
      'https://api.openai.com/v1/realtime/calls',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer ephemeral-secret' }),
        body: 'offer-sdp'
      })
    )
  })

  it('mints visual snapshot consent without adding a video media track', async () => {
    mockMintSession()

    const voice = usePatientRealtimeVoice()
    await voice.connect({
      patientToken: 'patient-token',
      visualSnapshotConsent: true
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/patient_agent/patient/sessions',
      expect.objectContaining({
        body: expect.objectContaining({ video_consent: true })
      })
    )
    expect(voice.visualSnapshotConsentEnabled.value).toBe(true)
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith(expect.objectContaining({
      video: false
    }))
  })

  it('authorizes and sends a consented patient-selected image as realtime input_image context', async () => {
    fetchMock
      .mockResolvedValueOnce(mintedSession())
      .mockResolvedValueOnce(visualAuthorization())

    const voice = usePatientRealtimeVoice()
    await voice.connect({
      patientToken: 'patient-token',
      visualSnapshotConsent: true
    })
    dataChannel.send.mockReset()

    const image = {
      type: 'image/png',
      size: 1024,
      name: 'mouth.png'
    } as File
    await voice.sendVisualSnapshot(image)

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/patient_agent/patient/sessions/session-1/visual-snapshots/authorize',
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer patient-token' },
        body: { mime_type: 'image/png', size_bytes: 1024 }
      })
    )
    expect(dataChannel.send).toHaveBeenCalledTimes(2)
    const createEvent = JSON.parse(dataChannel.send.mock.calls[0][0])
    expect(createEvent).toMatchObject({
      type: 'conversation.item.create',
      item: {
        type: 'message',
        role: 'user'
      }
    })
    expect(createEvent.item.content[0]).toEqual({
      type: 'input_image',
      image_url: 'data:image/png;base64,dGVzdC1pbWFnZQ==',
      detail: 'auto'
    })
    expect(createEvent.item.content[1].text).toContain('Do not diagnose')
    expect(dataChannel.send).toHaveBeenLastCalledWith(JSON.stringify({ type: 'response.create' }))
  })

  it('does not send provider image events when server authorization fails', async () => {
    fetchMock
      .mockResolvedValueOnce(mintedSession())
      .mockRejectedValueOnce(new Error('rate limited'))

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token', visualSnapshotConsent: true })
    dataChannel.send.mockReset()

    await expect(voice.sendVisualSnapshot({
      type: 'image/jpeg',
      size: 512,
      name: 'mouth.jpg'
    } as File)).rejects.toThrow('rate limited')
    expect(dataChannel.send).not.toHaveBeenCalled()
  })

  it('rejects visual snapshots when the session did not grant visual consent', async () => {
    mockMintSession()

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token' })
    dataChannel.send.mockReset()

    await expect(voice.sendVisualSnapshot({
      type: 'image/jpeg',
      size: 512,
      name: 'mouth.jpg'
    } as File)).rejects.toThrow('Visual snapshot consent was not granted')
    expect(dataChannel.send).not.toHaveBeenCalled()
  })

  it('rejects unsupported visual snapshot formats', async () => {
    mockMintSession()

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token', visualSnapshotConsent: true })
    dataChannel.send.mockReset()

    await expect(voice.sendVisualSnapshot({
      type: 'image/webp',
      size: 512,
      name: 'mouth.webp'
    } as File)).rejects.toThrow('PNG or JPEG')
    expect(dataChannel.send).not.toHaveBeenCalled()
  })

  it('bridges realtime dental knowledge calls through the authenticated patient endpoint', async () => {
    fetchMock
      .mockResolvedValueOnce(mintedSession())
      .mockResolvedValueOnce({
        data: {
          sources: [{
            entry_id: 'entry-1',
            topic: 'preventive_care',
            title: 'Brushing',
            content: 'Brush twice daily.',
            source_name: 'Clinic guide',
            source_reference: 'guide-1',
            locale: 'tr'
          }],
          fallback_required: false,
          patient_education_only: true
        }
      })

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token', locale: 'tr' })

    expect(dataChannel.onmessage).toBeTypeOf('function')
    dataChannel.onmessage?.({
      data: JSON.stringify({
        type: 'response.function_call_arguments.done',
        call_id: 'call-1',
        name: 'search_patient_dental_knowledge',
        arguments: JSON.stringify({ query: 'How should I brush?', topic: 'preventive_care' })
      })
    } as MessageEvent<string>)

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
      expect(dataChannel.send).toHaveBeenCalledTimes(2)
    })

    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/patient_agent/patient/knowledge/search',
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer patient-token' },
        body: {
          query: 'How should I brush?',
          locale: 'tr',
          topic: 'preventive_care',
          limit: 5
        }
      })
    )
    expect(dataChannel.send).toHaveBeenCalledWith(expect.stringContaining('function_call_output'))
    expect(dataChannel.send).toHaveBeenCalledWith(JSON.stringify({ type: 'response.create' }))
  })

  it('mutes and unmutes the microphone track', async () => {
    mockMintSession()

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token' })
    voice.setMuted(true)
    expect(track.enabled).toBe(false)
    voice.setMuted(false)
    expect(track.enabled).toBe(true)
  })
})
