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
    this.result = `data:${file.type};base64,dGVzdA==`
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

function visualConsentRevoked() {
  return {
    data: {
      session_id: 'session-1',
      consent_type: 'video',
      granted: false,
      scope: 'visual_snapshot_only',
      continuous_video: false
    }
  }
}

describe('usePatientRealtimeVoice visual revocation race guard', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    nativeFetch.mockClear()
    dataChannel.send.mockReset()
    dataChannel.close.mockReset()
    dataChannel.onerror = null
    dataChannel.onmessage = null
  })

  it('blocks image authorization and provider delivery while consent revocation is pending', async () => {
    let resolveRevocation: ((value: ReturnType<typeof visualConsentRevoked>) => void) | null = null
    const revocationPending = new Promise<ReturnType<typeof visualConsentRevoked>>((resolve) => {
      resolveRevocation = resolve
    })

    fetchMock
      .mockResolvedValueOnce(mintedSession())
      .mockReturnValueOnce(revocationPending)

    const voice = usePatientRealtimeVoice()
    await voice.connect({ patientToken: 'patient-token', visualSnapshotConsent: true })
    dataChannel.send.mockReset()

    const revokePromise = voice.stopVisualSnapshotSharing()
    expect(voice.isRevokingVisualSnapshotConsent.value).toBe(true)

    await expect(voice.sendVisualSnapshot({
      type: 'image/png',
      size: 1024,
      name: 'mouth.png'
    } as File)).rejects.toThrow('Visual snapshot sharing is stopping')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(dataChannel.send).not.toHaveBeenCalled()

    resolveRevocation?.(visualConsentRevoked())
    await revokePromise

    expect(voice.isRevokingVisualSnapshotConsent.value).toBe(false)
    expect(voice.visualSnapshotConsentEnabled.value).toBe(false)
  })
})
