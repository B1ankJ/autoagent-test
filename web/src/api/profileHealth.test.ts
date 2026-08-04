import { describe, expect, it } from 'vitest'
import { summarizeHealth } from './profileHealth'
import type { ProfileHealth } from '../types/api'

function row(status: ProfileHealth['status']): ProfileHealth {
  return {
    name: 'p',
    platform: 'api',
    status,
    success_rate: 1,
    total_runs: 1,
    avg_duration_ms: 100,
    unacked_anomalies: 0,
    devices_online: null,
    devices_total: null,
  }
}

describe('summarizeHealth', () => {
  it('counts by status', () => {
    expect(summarizeHealth([row('green'), row('green'), row('red'), row('nodata')])).toEqual({
      green: 2,
      yellow: 0,
      red: 1,
      nodata: 1,
    })
  })
})
