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

// Stream quality knobs forwarded to the backend as query params. width is the
// stream's pixel width (height scales to keep aspect); bitrateMbps caps the
// on-device H264 encoder. Lower both to cut latency / raise frame rate on
// wifi-adb devices, at the cost of sharpness. Omitting either uses the
// backend defaults (720px / 6Mbps).
export interface StreamQualityOptions {
  width?: number
  bitrateMbps?: number
}

// Shared quality presets. `balanced` omits both params so the backend applies
// its own defaults (720px / 6Mbps). `smooth` trades sharpness for lower latency
// / higher frame rate (best for wifi devices and the N-up grid); `sharp` is for
// reading fine text in the full single-device view.
export type StreamQualityKey = 'ultra' | 'smooth' | 'balanced' | 'sharp'

export const STREAM_QUALITY_PRESETS: Record<StreamQualityKey, StreamQualityOptions> = {
  // Smaller frames + lower bitrate = less to encode on-device, less to push
  // over adb, less to decode — so `ultra` has the lowest end-to-end latency
  // (at the cost of sharpness). Best for interacting, where seeing the result
  // fast matters more than a crisp image.
  ultra: { width: 360, bitrateMbps: 2 },
  smooth: { width: 540, bitrateMbps: 4 },
  balanced: {},
  sharp: { width: 1080, bitrateMbps: 12 },
}

/** Append width/bitrate params to a stream URL. Pure — unit-tested. */
export function appendStreamQuality(url: string, opts?: StreamQualityOptions): string {
  if (!opts) return url
  const parts: string[] = []
  if (opts.width != null) parts.push(`width=${opts.width}`)
  if (opts.bitrateMbps != null) parts.push(`bitrate=${opts.bitrateMbps}`)
  if (parts.length === 0) return url
  return `${url}&${parts.join('&')}`
}

const MAX_RETRIES = 3
const RETRY_DELAY_MS = 2000

// Every stream hook below closes its VideoDecoder from two independent
// places that can both fire on unmount: the effect cleanup, and the async
// read loop's own finally/onclose handler reacting to the abort/close that
// cleanup just triggered. WebCodecs throws InvalidStateError ("Cannot call
// 'close' on a closed codec") on a double-close, so whichever of those two
// runs second needs this guard instead of calling decoder.close() directly.
// Paint the canvas fully black. Called when a stream tears down (e.g. a grid
// card paused because its full-view modal opened) so the tile clearly reads as
// "disconnected" instead of freezing on its last decoded frame.
export function fillCanvasBlack(canvas: HTMLCanvasElement | null): void {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
}

export function safeCloseDecoder(decoder: VideoDecoder | null | undefined): void {
  if (!decoder || decoder.state === 'closed') return
  try {
    decoder.close()
  } catch {
    // Lost the race anyway (closed between the check above and this call) — ignore.
  }
}

export function useDeviceStream(
  serial: string | null,
  quality?: StreamQualityOptions,
): DeviceStreamHandle {
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
    const wsUrl = appendStreamQuality(
      `${proto}://${window.location.host}/api/v1/devices/${encodeURIComponent(serial)}/stream?token=${token}`,
      quality,
    )
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
        // Per the WebCodecs spec, a decode error closes the codec — without
        // reflecting that into `state`, the canvas just freezes on the last
        // frame with no error indicator and no way to trigger the existing
        // manual-reconnect affordance (DeviceStreamModal already renders one
        // for state === 'error', it just never got told this happened).
        console.error('VideoDecoder error', e)
        setState('error')
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
      safeCloseDecoder(decoder)
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
    // Depend on primitive quality values, not the object: an inline {width}
    // prop is a new ref every render and would reconnect on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serial, quality?.width, quality?.bitrateMbps])

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
      safeCloseDecoder(decoderRef.current)
    }
  }, [serial, connect])

  // Paint black once torn down (serial → null) — see the http hook's note.
  useEffect(() => {
    if (!serial) fillCanvasBlack(canvasRef.current)
  }, [serial])

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

export function useDeviceHttpStream(
  serial: string | null,
  quality?: StreamQualityOptions,
): DeviceStreamHandle {
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
      // See useDeviceStream's identical handler above for why this needs to
      // update `state`, not just log.
      error: (e) => {
        console.error('VideoDecoder error', e)
        setState('error')
      },
    })
    decoderRef.current = decoder

    const token = getToken()
    const url = appendStreamQuality(
      `/api/v1/devices/${encodeURIComponent(serial)}/stream.h264?token=${token}`,
      quality,
    )
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
        safeCloseDecoder(decoder)
        if (retryCount.current < MAX_RETRIES) {
          retryCount.current++
          setTimeout(connect, RETRY_DELAY_MS)
        } else {
          setState('error')
        }
      }
    })()
    // Depend on primitive quality values, not the object: an inline {width}
    // prop is a new ref every render and would reconnect on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serial, quality?.width, quality?.bitrateMbps])

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
      safeCloseDecoder(decoderRef.current)
    }
  }, [serial, connect])

  // Paint black once the stream is torn down (serial → null, e.g. this grid
  // card paused because its full-view modal opened) so it reads as
  // disconnected instead of freezing on its last frame.
  useEffect(() => {
    if (!serial) fillCanvasBlack(canvasRef.current)
  }, [serial])

  return { canvasRef, state, latencyMs, reconnect }
}

// Screenshot polling — works through any HTTP-only reverse proxy.
// Use when WebSocket H264 streaming is blocked by the network path.

export interface DeviceScreenshotHandle {
  imgRef: React.RefObject<HTMLImageElement>
  src: string | null
  state: StreamState
  reconnect: () => void
  // Wire these onto the <img> (onLoad/onError) — see the note on why the old
  // addEventListener approach could silently never attach.
  onLoad: () => void
  onError: () => void
}

const SCREENSHOT_INTERVAL_MS = 500

export function useDeviceScreenshot(
  serial: string | null,
  intervalMs: number = SCREENSHOT_INTERVAL_MS,
): DeviceScreenshotHandle {
  const imgRef = useRef<HTMLImageElement>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [state, setState] = useState<StreamState>('closed')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const failuresRef = useRef(0)
  // Read the live serial inside the self-scheduled callback without making
  // `tick` change identity (which would tear down/rebuild the loop).
  const serialRef = useRef(serial)
  serialRef.current = serial

  // Self-paced polling: fetch the *next* screenshot only after the current one
  // finishes (onLoad/onError), not on a blind fixed interval. A fixed interval
  // faster than the device's screencap latency kept swapping img.src before the
  // previous load completed, so the browser cancelled each in-flight load and
  // the frame never advanced — "直播中" but frozen. This paces requests to the
  // device's real speed so every frame completes and the image actually
  // updates.
  const tick = useCallback(() => {
    const s = serialRef.current
    if (!s) return
    const token = getToken()
    setSrc(`/api/v1/devices/${encodeURIComponent(s)}/screenshot.png?token=${token}&ts=${Date.now()}`)
  }, [])

  const scheduleNext = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(tick, intervalMs)
  }, [tick, intervalMs])

  const start = useCallback(() => {
    if (!serialRef.current) return
    failuresRef.current = 0
    setState('connecting')
    tick()
  }, [tick])

  useEffect(() => {
    if (!serial) {
      if (timerRef.current) clearTimeout(timerRef.current)
      setSrc(null)
      setState('closed')
      return
    }
    start()
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [serial, start])

  const onLoad = useCallback(() => {
    failuresRef.current = 0
    setState('live')
    scheduleNext()
  }, [scheduleNext])

  const onError = useCallback(() => {
    failuresRef.current += 1
    if (failuresRef.current >= 5) {
      setState('error') // give up chaining; reconnect() restarts
      return
    }
    scheduleNext()
  }, [scheduleNext])

  // onLoad/onError are returned for the consumer to bind as React <img> props.
  // The previous approach attached them via addEventListener in a one-shot
  // effect keyed on [onLoad, onError] (stable) — if imgRef.current was null
  // when it first ran (e.g. the <img> lives inside a destroyOnClose modal that
  // wasn't open yet), it bailed and never re-ran, so the listeners were never
  // attached and state was stuck on 'connecting'. React props bind regardless
  // of mount timing.
  return { imgRef, src, state, reconnect: start, onLoad, onError }
}
