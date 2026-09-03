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

const fetchMock = vi.fn()
vi.stubGlobal('$fetch', fetchMock)

class MockPeerConnection {
  connectionState = 'new'
  localDescription: RTCSessionDescriptionInit | null = null
  ontrack: ((event: RTCTrackEvent) => void) | null = null
  onconnectionstatechange: (() => void) | null = null
  addTrack = vi.fn()
  createDataChannel = vi.fn(() => ({ close: vi.fn(), onerror: null }))
  createOffer = vi.fn(async () => ({ type: 'offer', sdp: 'offer-sdp' }))
  setLocalDescription = vi.fn(async (description) => {
    this.localDescription = description
  })
  setRemoteDescription = vi.fn(async () => undefined)
  close = vi.fn()
}

const peer = new MockPeerConnection()
vi.stubGlobal('RTCPeerConnection', vi.fn(() => peer))

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

describe('usePatientRealtimeVoice', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    nativeFetch.mockClear()
    track.enabled = true
  })

  it('mints a voice session with AI/audio consent and no video consent', async () => {
    fetchMock.mockResolvedValue({
      data: {
        session_id: 'session-1',
        channel: 'voice',
        provider: 'openai',
        client_secret: 'ephemeral-secret',
        expires_at_epoch: 123
      }
    })

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
    expect(nativeFetch).toHaveBeenCalledWith(
      'https://api.openai.com/v1/realtime/calls',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer ephemeral-secret' }),
        body: 'offer-sdp'
      })
    )
  })

  it('mutes and unmutes the microphone track', async () => {
    fetchMock.mockResolvedValue({
      data: {
        session_id: 'session-1',
        channel: 'voice',
        provider: 'openai',
        client_secret: 'ephemeral-secret',
        expires_at_epoch: 123
      }
    })

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token' })
    voice.setMuted(true)
    expect(track.enabled).toBe(false)
    voice.setMuted(false)
    expect(track.enabled).toBe(true)
  })
})
