import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { clearReloadGuard, installStaleChunkReload } from './staleChunkReload'

let unsubscribe: (() => void) | undefined
let reload: ReturnType<typeof vi.fn>

beforeEach(() => {
  sessionStorage.clear()
  reload = vi.fn()
  Object.defineProperty(window, 'location', {
    value: { ...window.location, reload },
    writable: true,
    configurable: true,
  })
})

afterEach(() => {
  unsubscribe?.()
})

it('reloads once when a preload error fires', () => {
  unsubscribe = installStaleChunkReload()
  const event = new Event('vite:preloadError', { cancelable: true })

  window.dispatchEvent(event)

  expect(reload).toHaveBeenCalledTimes(1)
  expect(event.defaultPrevented).toBe(true)
})

it('does not reload a second time in the same session (avoids a reload loop)', () => {
  unsubscribe = installStaleChunkReload()

  window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))
  window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))

  expect(reload).toHaveBeenCalledTimes(1)
})

it('clearReloadGuard lets a future deploy trigger another automatic reload', () => {
  unsubscribe = installStaleChunkReload()

  window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))
  clearReloadGuard()
  window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))

  expect(reload).toHaveBeenCalledTimes(2)
})

it('does not reload once unsubscribed', () => {
  unsubscribe = installStaleChunkReload()
  unsubscribe()

  window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))

  expect(reload).not.toHaveBeenCalled()
})
