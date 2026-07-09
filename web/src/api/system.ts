import { useMutation, useQuery } from '@tanstack/react-query'
import { client } from './client'

export interface UpdateStatus {
  enabled: boolean
  current_commit: string | null
  current_short: string | null
  remote_commit: string | null
  remote_short: string | null
  behind: number
  up_to_date: boolean
  changelog: string[]
  fetch_ok: boolean
  error: string | null
}

export interface ApplyResult {
  ok: boolean
  restarting: boolean
  steps: string[]
  error: string | null
  active_batches: number
}

/** Cached local-vs-remote status (no network fetch). Polled by the nav badge. */
export function useUpdateStatus(enabled = true) {
  return useQuery({
    queryKey: ['system', 'update', 'status'],
    queryFn: async () => (await client.get<UpdateStatus>('/system/update/status')).data,
    enabled,
    refetchInterval: 60_000,
  })
}

/** Fetch origin/main and report availability. */
export function useCheckUpdate() {
  return useMutation({
    mutationFn: async () =>
      (await client.post<UpdateStatus>('/system/update/check')).data,
  })
}

/** Pull + rebuild + restart. force=true interrupts in-flight batches. */
export function useApplyUpdate() {
  return useMutation({
    mutationFn: async (force: boolean) =>
      (await client.post<ApplyResult>('/system/update/apply', { force })).data,
  })
}

export interface HealthInfo {
  status: string
  commit: string | null
}

/** Raw /health probe used to detect when a restart has landed. */
export async function probeHealth(): Promise<HealthInfo | null> {
  try {
    const res = await client.get<HealthInfo>('/health', {
      baseURL: '/',
      timeout: 4000,
    })
    return res.data
  } catch {
    return null
  }
}
