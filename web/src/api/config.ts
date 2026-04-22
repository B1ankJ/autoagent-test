import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GlobalDefaults, VLMConfig } from '../types/api'
import { client } from './client'

export function useVLM() {
  return useQuery({
    queryKey: ['config', 'vlm'],
    queryFn: async () => (await client.get<VLMConfig>('/config/vlm')).data,
  })
}

export function useSaveVLM() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (body: VLMConfig) => (await client.put('/config/vlm', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['config', 'vlm'] }),
  })
}

export function useDefaults() {
  return useQuery({
    queryKey: ['config', 'defaults'],
    queryFn: async () => (await client.get<GlobalDefaults>('/config/defaults')).data,
  })
}

export function useSaveDefaults() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (body: GlobalDefaults) => (await client.put('/config/defaults', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['config', 'defaults'] }),
  })
}
