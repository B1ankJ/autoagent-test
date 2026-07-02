import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ProfileSummary, ValidateResponse } from '../types/api'
import { client } from './client'

export interface DeviceInitState {
  serial: string
  status: 'pending' | 'running' | 'done' | 'failed'
  rebooted: boolean
  steps_run: number
  duration_ms: number
  error: string | null
}

export interface InitJob {
  id: string
  profile_name: string
  finished: boolean
  devices: DeviceInitState[]
}

export function useProfiles() {
  return useQuery({
    queryKey: ['profiles'],
    queryFn: async () => (await client.get<ProfileSummary[]>('/profiles')).data,
  })
}

export function useProfile(name: string | undefined) {
  return useQuery({
    queryKey: ['profile', name],
    queryFn: async () => (await client.get<{ yaml: string }>(`/profiles/${name}`)).data,
    enabled: !!name,
  })
}

export function useSaveProfile() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (args: { name: string; yaml: string; create: boolean }) => {
      const url = `/profiles/${args.name}`
      return args.create
        ? (await client.post(url, { yaml: args.yaml })).data
        : (await client.put(url, { yaml: args.yaml })).data
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] })
      queryClient.invalidateQueries({ queryKey: ['profile', variables.name] })
    },
  })
}

export function useDeleteProfile() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (name: string) => {
      await client.delete(`/profiles/${name}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profiles'] }),
  })
}

export function useValidateProfile() {
  return useMutation({
    mutationFn: async (yaml: string) =>
      (await client.post<ValidateResponse>('/profiles/validate', { yaml })).data,
  })
}

export function useInitializeDevices() {
  return useMutation({
    mutationFn: async (args: { name: string; serials: string[]; reboot?: boolean | null }) =>
      (
        await client.post<InitJob>(`/profiles/${args.name}/initialize`, {
          serials: args.serials,
          reboot: args.reboot ?? null,
        })
      ).data,
  })
}

export function useInitJob(jobId: string | null) {
  return useQuery({
    queryKey: ['init-job', jobId],
    queryFn: async () => (await client.get<InitJob>(`/profiles/initialize/${jobId}`)).data,
    enabled: !!jobId,
    // Poll while running; stop once the backend reports finished.
    refetchInterval: (query) => (query.state.data?.finished ? false : 1500),
  })
}

export function useSaveProfileDevices() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (args: { name: string; serials: string[] }) =>
      (
        await client.put<{ name: string; serials: string[] }>(
          `/profiles/${args.name}/devices`,
          { serials: args.serials },
        )
      ).data,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] })
      queryClient.invalidateQueries({ queryKey: ['profile', variables.name] })
    },
  })
}
