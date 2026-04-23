import { describe, expect, it } from 'vitest'

import { useDevices } from './devices'

describe('devices api', () => {
  it('exports the devices hook', () => {
    expect(typeof useDevices).toBe('function')
  })
})
