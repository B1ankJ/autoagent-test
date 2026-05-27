import { useCallback, useEffect, useRef, useState } from 'react'

import { client, getToken } from './client'
import type { DeviceInputRequest } from '../types/api'

export type StreamState = 'connecting' | 'live' | 'error' | 'unsupported' | 'closed'

export interface DeviceStreamHandle {
  canvasRef: React.RefObject<HTMLCanvasElement>
  state: StreamState
  latencyMs: number | null
  reconnect: () => void
}

const MAX_RETRIES = 3
const RETRY_DELAY_MS = 2000

export function useDeviceStream(serial: string | null): DeviceStreamHandle {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [state, setState] = useState<StreamState>('closed')
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const retryCount = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const decoderRef = useRef<VideoDecoder | null>(null)
  const bufferRef = useRef<Uint8Array>(new Uint8Array(0))
  const spsRef = useRef<Uint8Array | null>(null)
  const ppsRef = useRef<Uint8Array | null>(null)
  const frameCountRef = useRef(0)
  const frameTimestampRef = useRef(0)

  const connect = useCallback(() => {
    if (!serial) return
    if (typeof VideoDecoder === 'undefined') {
      setState('unsupported')
      return
    }

    setState('connecting')
    const token = getToken()
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${proto}://${window.location.host}/api/v1/devices/${encodeURIComponent(serial)}/stream?token=${token}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    ws.binaryType = 'arraybuffer'

    bufferRef.current = new Uint8Array(0)
    spsRef.current = null
    ppsRef.current = null
    frameCountRef.current = 0
    frameTimestampRef.current = 0

    const decoder = new VideoDecoder({
      output: (frame) => {
        const canvas = canvasRef.current
        if (canvas) {
          canvas.width = frame.displayWidth
          canvas.height = frame.displayHeight
          const ctx = canvas.getContext('2d')
          ctx?.drawImage(frame, 0, 0)
        }
        frame.close()
      },
      error: (e) => {
        console.error('VideoDecoder error', e)
      },
    })
    decoderRef.current = decoder

    ws.onopen = () => {
      retryCount.current = 0
      setState('live')
    }

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data)
          console.warn('[stream] control frame:', msg)
          if (msg.error) setState('error')
        } catch {
          // ignore malformed control frames
        }
        return
      }

      const incoming = new Uint8Array(event.data as ArrayBuffer)
      const combined = new Uint8Array(bufferRef.current.length + incoming.length)
      combined.set(bufferRef.current)
      combined.set(incoming, bufferRef.current.length)

      bufferRef.current = parseAndDecodeNALUs(
        combined,
        decoder,
        spsRef,
        ppsRef,
        frameCountRef,
        frameTimestampRef,
        setLatencyMs,
      )
    }

    ws.onclose = () => {
      decoder.close()
      if (retryCount.current < MAX_RETRIES) {
        retryCount.current++
        setTimeout(connect, RETRY_DELAY_MS)
      } else {
        setState('error')
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [serial])

  const reconnect = useCallback(() => {
    retryCount.current = 0
    wsRef.current?.close()
    connect()
  }, [connect])

  useEffect(() => {
    if (!serial) return
    connect()
    return () => {
      retryCount.current = MAX_RETRIES
      wsRef.current?.close()
      decoderRef.current?.close()
    }
  }, [serial, connect])

  return { canvasRef, state, latencyMs, reconnect }
}

function findStartCodes(data: Uint8Array): number[] {
  const positions: number[] = []
  for (let i = 0; i < data.length - 3; i++) {
    if (data[i] === 0 && data[i + 1] === 0) {
      if (data[i + 2] === 0 && data[i + 3] === 1) {
        positions.push(i)
        i += 3
      } else if (data[i + 2] === 1) {
        positions.push(i)
        i += 2
      }
    }
  }
  return positions
}

// Extract codec string from SPS NALU: avc1.PPCCLL
function codecFromSPS(sps: Uint8Array): string {
  if (sps.length < 4) return 'avc1.640028'
  const p = sps[1].toString(16).padStart(2, '0')
  const c = sps[2].toString(16).padStart(2, '0')
  const l = sps[3].toString(16).padStart(2, '0')
  return `avc1.${p}${c}${l}`
}

function annexBNAL(nalu: Uint8Array): Uint8Array {
  const out = new Uint8Array(4 + nalu.length)
  out.set([0, 0, 0, 1])
  out.set(nalu, 4)
  return out
}

// Returns remaining unprocessed tail of the buffer (from last incomplete NAL start code).
// IDR keyframes are bundled as SPS+PPS+IDR in a single EncodedVideoChunk so the decoder
// receives a complete Access Unit, which is required by the WebCodecs VideoDecoder spec.
function parseAndDecodeNALUs(
  buffer: Uint8Array,
  decoder: VideoDecoder,
  spsRef: React.MutableRefObject<Uint8Array | null>,
  ppsRef: React.MutableRefObject<Uint8Array | null>,
  frameCountRef: React.MutableRefObject<number>,
  frameTimestampRef: React.MutableRefObject<number>,
  setLatencyMs: (ms: number) => void,
): Uint8Array {
  const starts = findStartCodes(buffer)
  if (starts.length < 2) return buffer

  for (let i = 0; i < starts.length - 1; i++) {
    const scStart = starts[i]
    const scLen = buffer[scStart + 2] === 1 ? 3 : 4
    const nalStart = scStart + scLen
    const nalEnd = starts[i + 1]
    if (nalEnd <= nalStart) continue

    const nalu = buffer.slice(nalStart, nalEnd)
    if (nalu.length === 0) continue
    const nalType = nalu[0] & 0x1f

    if (nalType === 7) {
      // SPS — store and configure decoder
      spsRef.current = nalu
      if (decoder.state === 'unconfigured') {
        const codec = codecFromSPS(nalu)
        console.log('[stream] SPS received, configuring decoder codec=', codec, 'sps=', Array.from(nalu.slice(0,8)).map(b=>b.toString(16).padStart(2,'0')).join(' '))
        try {
          decoder.configure({ codec, optimizeForLatency: true })
          console.log('[stream] decoder state after configure:', decoder.state)
        } catch (e) {
          console.error('[stream] VideoDecoder configure failed', e)
        }
      }
    } else if (nalType === 8) {
      // PPS — just store; configure was triggered by SPS
      ppsRef.current = nalu
    } else if (nalType === 5 && decoder.state === 'configured') {
      // IDR keyframe: bundle SPS + PPS + IDR as a single Access Unit
      const sps = spsRef.current
      const pps = ppsRef.current
      const parts = sps && pps
        ? [annexBNAL(sps), annexBNAL(pps), annexBNAL(nalu)]
        : [annexBNAL(nalu)]
      const totalLen = parts.reduce((s, p) => s + p.length, 0)
      const chunkData = new Uint8Array(totalLen)
      let off = 0
      for (const p of parts) { chunkData.set(p, off); off += p.length }

      const ts = frameTimestampRef.current
      frameTimestampRef.current += 33333
      frameCountRef.current++
      if (frameCountRef.current <= 3) console.log('[stream] IDR keyframe #', frameCountRef.current, 'chunkLen=', chunkData.length, 'decoderState=', decoder.state)
      const wallStart = performance.now()
      decoder.decode(new EncodedVideoChunk({ type: 'key', timestamp: ts, data: chunkData }))
      if (frameCountRef.current % 30 === 0) setLatencyMs(Math.round(performance.now() - wallStart + 33))
    } else if (nalType === 1 && decoder.state === 'configured') {
      // Non-IDR slice
      const ts = frameTimestampRef.current
      frameTimestampRef.current += 33333
      frameCountRef.current++
      decoder.decode(new EncodedVideoChunk({ type: 'delta', timestamp: ts, data: annexBNAL(nalu) }))
    }
  }

  // Keep only the tail starting from the last start code (may be incomplete)
  return buffer.slice(starts[starts.length - 1])
}

export async function postDeviceInput(serial: string, cmd: DeviceInputRequest): Promise<void> {
  await client.post(`/devices/${serial}/input`, cmd)
}

// H.264 over HTTP chunked — same capture pipeline as the WebSocket
// streamer, but the transport is plain HTTP so it works through L7
// reverse proxies that strip WebSocket Upgrade headers. Browser uses
// WebCodecs VideoDecoder via the existing NAL parser.

export function useDeviceHttpStream(serial: string | null): DeviceStreamHandle {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [state, setState] = useState<StreamState>('closed')
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const retryCount = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const decoderRef = useRef<VideoDecoder | null>(null)
  const bufferRef = useRef<Uint8Array>(new Uint8Array(0))
  const spsRef = useRef<Uint8Array | null>(null)
  const ppsRef = useRef<Uint8Array | null>(null)
  const frameCountRef = useRef(0)
  const frameTimestampRef = useRef(0)

  const connect = useCallback(() => {
    if (!serial) return
    if (typeof VideoDecoder === 'undefined') {
      setState('unsupported')
      return
    }

    setState('connecting')
    bufferRef.current = new Uint8Array(0)
    spsRef.current = null
    ppsRef.current = null
    frameCountRef.current = 0
    frameTimestampRef.current = 0

    const decoder = new VideoDecoder({
      output: (frame) => {
        const canvas = canvasRef.current
        if (canvas) {
          canvas.width = frame.displayWidth
          canvas.height = frame.displayHeight
          const ctx = canvas.getContext('2d')
          ctx?.drawImage(frame, 0, 0)
        }
        frame.close()
      },
      error: (e) => console.error('VideoDecoder error', e),
    })
    decoderRef.current = decoder

    const token = getToken()
    const url = `/api/v1/devices/${encodeURIComponent(serial)}/stream.h264?token=${token}`
    const ctrl = new AbortController()
    abortRef.current = ctrl

    ;(async () => {
      try {
        const resp = await fetch(url, { signal: ctrl.signal })
        if (!resp.ok || !resp.body) {
          setState('error')
          return
        }
        retryCount.current = 0
        setState('live')
        const reader = resp.body.getReader()
        for (;;) {
          const { value, done } = await reader.read()
          if (done) break
          if (!value || value.length === 0) continue
          const combined = new Uint8Array(bufferRef.current.length + value.length)
          combined.set(bufferRef.current)
          combined.set(value, bufferRef.current.length)
          bufferRef.current = parseAndDecodeNALUs(
            combined,
            decoder,
            spsRef,
            ppsRef,
            frameCountRef,
            frameTimestampRef,
            setLatencyMs,
          )
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        console.warn('[http-stream] read failed', err)
      } finally {
        try {
          decoder.close()
        } catch {
          // ignore
        }
        if (retryCount.current < MAX_RETRIES) {
          retryCount.current++
          setTimeout(connect, RETRY_DELAY_MS)
        } else {
          setState('error')
        }
      }
    })()
  }, [serial])

  const reconnect = useCallback(() => {
    retryCount.current = 0
    abortRef.current?.abort()
    connect()
  }, [connect])

  useEffect(() => {
    if (!serial) return
    connect()
    return () => {
      retryCount.current = MAX_RETRIES
      abortRef.current?.abort()
      decoderRef.current?.close()
    }
  }, [serial, connect])

  return { canvasRef, state, latencyMs, reconnect }
}

// Screenshot polling — works through any HTTP-only reverse proxy.
// Use when WebSocket H264 streaming is blocked by the network path.

export interface DeviceScreenshotHandle {
  imgRef: React.RefObject<HTMLImageElement>
  src: string | null
  state: StreamState
  reconnect: () => void
}

const SCREENSHOT_INTERVAL_MS = 500

export function useDeviceScreenshot(serial: string | null): DeviceScreenshotHandle {
  const imgRef = useRef<HTMLImageElement>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [state, setState] = useState<StreamState>('closed')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const failuresRef = useRef(0)

  const tick = useCallback(() => {
    if (!serial) return
    const token = getToken()
    setSrc(
      `/api/v1/devices/${encodeURIComponent(serial)}/screenshot.png?token=${token}&ts=${Date.now()}`,
    )
  }, [serial])

  const start = useCallback(() => {
    if (!serial) return
    setState('connecting')
    failuresRef.current = 0
    tick()
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(tick, SCREENSHOT_INTERVAL_MS)
  }, [serial, tick])

  useEffect(() => {
    if (!serial) {
      setSrc(null)
      setState('closed')
      return
    }
    start()
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [serial, start])

  const onLoad = useCallback(() => {
    failuresRef.current = 0
    setState('live')
  }, [])

  const onError = useCallback(() => {
    failuresRef.current += 1
    if (failuresRef.current >= 5) setState('error')
  }, [])

  // Attach load/error listeners by mutating the ref's current element each tick.
  useEffect(() => {
    const img = imgRef.current
    if (!img) return
    img.addEventListener('load', onLoad)
    img.addEventListener('error', onError)
    return () => {
      img.removeEventListener('load', onLoad)
      img.removeEventListener('error', onError)
    }
  }, [onLoad, onError])

  return { imgRef, src, state, reconnect: start }
}
