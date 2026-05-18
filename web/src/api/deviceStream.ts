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
        try {
          decoder.configure({ codec: codecFromSPS(nalu), optimizeForLatency: true })
        } catch (e) {
          console.error('VideoDecoder configure failed', e)
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
