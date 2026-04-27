import { describe, expect, it } from 'vitest'

import { useDevices, useInstallAdbKeyboard } from './devices'

describe('devices api', () => {
  it('exports the devices hook', () => {
    expect(typeof useDevices).toBe('function')
  })

  it('exports the install adb keyboard hook', () => {
    expect(typeof useInstallAdbKeyboard).toBe('function')
  })
})
