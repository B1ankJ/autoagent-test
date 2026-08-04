import { useQuery } from '@tanstack/react-query'
import { HealthStatus, ProfileHealth } from '../types/api'
import { client } from './client'

export function useProfileHealth() {
  return useQuery({
    queryKey: ['profiles', 'health'],
    queryFn: async () => (await client.get<ProfileHealth[]>('/profiles/health')).data,
  })
}

export function summarizeHealth(rows: ProfileHealth[]): Record<HealthStatus, number> {
  const out: Record<HealthStatus, number> = { green: 0, yellow: 0, red: 0, nodata: 0 }
  for (const r of rows) out[r.status] += 1
  return out
}
