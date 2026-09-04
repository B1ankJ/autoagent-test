import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  appendStreamQuality,
  fillCanvasBlack,
  safeCloseDecoder,
  useDeviceHttpStream,
  useDeviceScreenshot,
} from './deviceStream'

describe('fillCanvasBlack', () => {
  it('paints the whole canvas black', () => {
    const fillRect = vi.fn()
    const canvas = {
      width: 320,
      height: 640,
      getContext: () => ({ fillStyle: '', fillRect }),
    } as unknown as HTMLCanvasElement
    fillCanvasBlack(canvas)
    expect(fillRect).toHaveBeenCalledWith(0, 0, 320, 640)
  })

  it('is a no-op for a null canvas', () => {
    expect(() => fillCanvasBlack(null)).not.toThrow()
  })
})

describe('useDeviceScreenshot', () => {
  it('goes from connecting to live when onLoad fires (regression: listeners once never attached)', () => {
    localStorage.setItem('autoagent_token', 'tok')
    // large interval so the poll timer doesn't churn during the test
    const { result } = renderHook(() => useDeviceScreenshot('emulator-5554', 1_000_000))
    expect(result.current.state).toBe('connecting')
    act(() => result.current.onLoad())
    expect(result.current.state).toBe('live')
    localStorage.clear()
  })

  it('self-paces: fetches the next screenshot only after the current one loads', () => {
    // Regression: a blind fixed interval swapped img.src before the previous
    // (slow) screencap finished, so the browser cancelled it and the frame
    // never advanced despite "直播中". Now the next fetch is scheduled from
    // onLoad, so the src only advances after a load completes.
    vi.useFakeTimers()
    localStorage.setItem('autoagent_token', 'tok')
    const { result } = renderHook(() => useDeviceScreenshot('emulator-5554', 300))
    const first = result.current.src
    expect(first).toBeTruthy()

    // No new fetch until the current one reports done — advancing time alone
    // does nothing while we're still "loading".
    act(() => vi.advanceTimersByTime(1000))
    expect(result.current.src).toBe(first)

    // Load completes → next fetch scheduled → advances after the interval.
    act(() => result.current.onLoad())
    act(() => vi.advanceTimersByTime(300))
    expect(result.current.src).not.toBe(first)

    vi.useRealTimers()
    localStorage.clear()
  })
})

describe('appendStreamQuality', () => {
  const base = '/api/v1/devices/x/stream.h264?token=t'

  it('returns the url unchanged when no options given', () => {
    expect(appendStreamQuality(base)).toBe(base)
    expect(appendStreamQuality(base, {})).toBe(base)
  })

  it('appends width and bitrate when provided', () => {
    expect(appendStreamQuality(base, { width: 540, bitrateMbps: 4 })).toBe(
      `${base}&width=540&bitrate=4`,
    )
  })

  it('appends only the params that are set', () => {
    expect(appendStreamQuality(base, { width: 720 })).toBe(`${base}&width=720`)
    expect(appendStreamQuality(base, { bitrateMbps: 8 })).toBe(`${base}&bitrate=8`)
  })
})

describe('safeCloseDecoder', () => {
  it('does not throw when called twice on the same decoder (unmount-cleanup vs. read-loop race)', () => {
    let state: 'unconfigured' | 'configured' | 'closed' = 'configured'
    const close = vi.fn(() => {
      if (state === 'closed') {
        throw new DOMException("Cannot call 'close' on a closed codec.", 'InvalidStateError')
      }
      state = 'closed'
    })
    const decoder = {
      get state() {
        return state
      },
      close,
    } as unknown as VideoDecoder

    expect(() => safeCloseDecoder(decoder)).not.toThrow()
    expect(() => safeCloseDecoder(decoder)).not.toThrow()
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('is a no-op for a null or undefined decoder', () => {
    expect(() => safeCloseDecoder(null)).not.toThrow()
    expect(() => safeCloseDecoder(undefined)).not.toThrow()
  })

  it('swallows a throw even if state somehow lags behind an already-closed decoder', () => {
    const close = vi.fn(() => {
      throw new DOMException("Cannot call 'close' on a closed codec.", 'InvalidStateError')
    })
    const decoder = { state: 'configured', close } as unknown as VideoDecoder

    expect(() => safeCloseDecoder(decoder)).not.toThrow()
    expect(close).toHaveBeenCalledTimes(1)
  })
})

describe('useDeviceHttpStream', () => {
  let capturedErrorHandler: ((e: unknown) => void) | null = null

  beforeEach(() => {
    localStorage.setItem('autoagent_token', 'tok')
    capturedErrorHandler = null

    class FakeVideoDecoder {
      state: 'unconfigured' | 'configured' | 'closed' = 'unconfigured'
      constructor(init: { output: (frame: unknown) => void; error: (e: unknown) => void }) {
        capturedErrorHandler = init.error
      }
      configure() {
        this.state = 'configured'
      }
      decode() {}
      close() {
        this.state = 'closed'
      }
    }
    vi.stubGlobal('VideoDecoder', FakeVideoDecoder)

    // A body stream that never resolves — the read loop just awaits forever,
    // which is fine: this test only needs the hook past the point where the
    // VideoDecoder gets constructed, not an actual completed stream.
    const body = new ReadableStream<Uint8Array>({
      start() {
        /* never enqueue, never close */
      },
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(body, { status: 200 })),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('sets state to "error" when the VideoDecoder reports a decode error, instead of just logging it', async () => {
    // Regression: per the WebCodecs spec, a decode error closes the codec,
    // but the error callback only did console.error — `state` never
    // reflected it, so the canvas silently froze on the last frame with no
    // error indicator and no way to reach the existing manual-reconnect
    // affordance (DeviceStreamModal already renders one for state==='error').
    const { result } = renderHook(() => useDeviceHttpStream('emulator-5554'))

    await waitFor(() => expect(capturedErrorHandler).not.toBeNull())
    await waitFor(() => expect(result.current.state).toBe('live'))

    act(() => capturedErrorHandler!(new DOMException('decode failed', 'EncodingError')))

    await waitFor(() => expect(result.current.state).toBe('error'))
  })
})
