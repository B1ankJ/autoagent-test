import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GlobalDefaults, VLMConfig } from '../types/api'
import { client } from './client'
import { parseContentDisposition, triggerDownload } from '../utils/download'

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
  empty_response_auto_reinit: boolean
  same_response_enabled: boolean
  same_response_threshold: number
  same_response_auto_reinit: boolean
  anr_check_enabled: boolean
  at_mobiles: string[]
  at_all: boolean
  app_base_url: string
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

/** Whitelist and blacklist share the exact same shape/endpoints (list/add/
 * remove), differing only in kv key server-side and in meaning: whitelist
 * entries suppress rule-2 alerts, blacklist entries skip straight past the
 * VLM judge and alert immediately on a repeat. */
function makeResponseListHooks(kind: 'whitelist' | 'blacklist') {
  const queryKey = ['config', 'notifications', kind]
  const basePath = `/config/notifications/${kind}`

  function useList() {
    return useQuery({
      queryKey,
      queryFn: async () => (await client.get<WhitelistEntry[]>(basePath)).data,
    })
  }

  function useAdd() {
    const queryClient = useQueryClient()
    return useMutation({
      mutationFn: async (body: { target_profile: string; response: string }) =>
        (await client.post(`${basePath}/add`, body)).data,
      onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    })
  }

  function useRemove() {
    const queryClient = useQueryClient()
    return useMutation({
      mutationFn: async (body: { target_profile: string; response: string }) =>
        (await client.post(`${basePath}/remove`, body)).data,
      onSuccess: () => queryClient.invalidateQueries({ queryKey }),
    })
  }

  return { useList, useAdd, useRemove }
}

const whitelistHooks = makeResponseListHooks('whitelist')
const blacklistHooks = makeResponseListHooks('blacklist')

export const useWhitelist = whitelistHooks.useList
export const useAddWhitelist = whitelistHooks.useAdd
export const useRemoveWhitelist = whitelistHooks.useRemove

export const useBlacklist = blacklistHooks.useList
export const useAddBlacklist = blacklistHooks.useAdd
export const useRemoveBlacklist = blacklistHooks.useRemove

export interface LogCleanupReport {
  files_deleted: number
  dirs_deleted: number
  bytes_freed: number
  batches_pruned: number
  batches_archived: number
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

export interface BackupInfo {
  name: string
  bytes: number
  created_at: string
}

export interface BackupRunResult {
  path: string | null
  bytes_written: number
  pruned: number
}

export function useBackupList() {
  return useQuery({
    queryKey: ['config', 'backup', 'list'],
    queryFn: async () => (await client.get<BackupInfo[]>('/config/backup/list')).data,
  })
}

export function useRunBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await client.post<BackupRunResult>('/config/backup/run')).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['config', 'backup', 'list'] }),
  })
}

export async function downloadBackup(name: string): Promise<void> {
  const response = await client.get(`/config/backup/download/${encodeURIComponent(name)}`, {
    responseType: 'blob',
  })
  const filename = parseContentDisposition(response.headers['content-disposition']) ?? name
  triggerDownload(response.data as Blob, filename)
}

export function useDeleteBackup() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      await client.delete(`/config/backup/${encodeURIComponent(name)}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['config', 'backup', 'list'] }),
  })
}

