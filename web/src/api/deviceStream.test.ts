import { describe, expect, it, vi } from 'vitest'

import { safeCloseDecoder } from './deviceStream'

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
