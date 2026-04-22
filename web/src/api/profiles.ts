import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ProfileSummary, ValidateResponse } from '../types/api'
import { client } from './client'

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
