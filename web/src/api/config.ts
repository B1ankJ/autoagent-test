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

export interface DingTalkConfig {
  enabled: boolean
  webhook_url: string
  secret: string
  empty_response_threshold: number
  same_response_enabled: boolean
  same_response_threshold: number
  same_response_auto_reinit: boolean
  at_mobiles: string[]
  at_all: boolean
}

export interface WhitelistEntry {
  target_profile: string
  response: string
  response_excerpt: string
  added_at: string
}

export interface DingTalkSendResult {
  ok: boolean
  status_code: number | null
  errcode: number | null
  errmsg: string | null
}

export function useNotifications() {
  return useQuery({
    queryKey: ['config', 'notifications'],
    queryFn: async () => (await client.get<DingTalkConfig>('/config/notifications')).data,
  })
}

export function useSaveNotifications() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: DingTalkConfig) =>
      (await client.put<DingTalkConfig>('/config/notifications', body)).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['config', 'notifications'] }),
  })
}

export function useTestNotifications() {
  return useMutation({
    mutationFn: async (body: DingTalkConfig) =>
      (await client.post<DingTalkSendResult>('/config/notifications/test', body)).data,
  })
}

export function useWhitelist() {
  return useQuery({
    queryKey: ['config', 'notifications', 'whitelist'],
    queryFn: async () =>
      (await client.get<WhitelistEntry[]>('/config/notifications/whitelist')).data,
  })
}

export interface LogCleanupReport {
  files_deleted: number
  dirs_deleted: number
  bytes_freed: number
  retention_days: number
}

export function usePreviewLogsCleanup() {
  return useMutation({
    mutationFn: async (days?: number) =>
      (
        await client.get<LogCleanupReport>('/config/logs/preview', {
          params: days ? { days } : {},
        })
      ).data,
  })
}

export function useRunLogsCleanup() {
  return useMutation({
    mutationFn: async (days?: number) =>
      (
        await client.post<LogCleanupReport>(
          '/config/logs/cleanup',
          null,
          { params: days ? { days } : {} },
        )
      ).data,
  })
}

export function useRemoveWhitelist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { target_profile: string; response: string }) =>
      (await client.post('/config/notifications/whitelist/remove', body)).data,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['config', 'notifications', 'whitelist'] }),
  })
}
