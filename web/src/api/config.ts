import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GlobalDefaults, VLMConfig } from '../types/api'
import { client } from './client'

export interface LLMCheckResult {
  ok: boolean
  stage: 'connect' | 'auth' | 'model_not_found' | 'response_shape' | 'ok'
  message: string
  latency_ms: number
}

export function useVLM() {
  return useQuery({
    queryKey: ['config', 'vlm'],
    queryFn: async () => (await client.get<VLMConfig | null>('/config/vlm')).data,
  })
}

export function useSaveVLM() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (body: VLMConfig) => (await client.put('/config/vlm', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['config', 'vlm'] }),
  })
}

export function useTestLLM() {
  return useMutation({
    mutationFn: async (body: { base_url: string; model: string; api_key: string }) =>
      (await client.post<LLMCheckResult>('/config/vlm/test', body)).data,
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
