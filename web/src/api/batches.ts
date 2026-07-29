import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BatchCreatedResponse,
  BatchCreateJSON,
  BatchDetail,
  ExecutionMode,
  BatchStatus,
  BatchSummary,
  SessionTurn,
} from '../types/api'
import { client } from './client'
import { parseContentDisposition, triggerDownload } from '../utils/download'
export { useBatchStream } from '../hooks/useBatchStream'

interface BatchQueryFilters {
  limit?: number
  offset?: number
  q?: string
  createdAfter?: string
  createdBefore?: string
  targetProfile?: string
  deviceSerial?: string
  emptyResponseOnly?: boolean
  excludeEndSession?: boolean
  durationAnomalyOnly?: boolean
  status?: BatchStatus[]
  mode?: ExecutionMode[]
}

function buildBatchParams(p: BatchQueryFilters) {
  const params: Record<string, string | number | boolean | string[]> = {}
  if (p.limit !== undefined) params.limit = p.limit
  if (p.offset !== undefined) params.offset = p.offset
  const q = p.q?.trim()
  if (q) params.q = q
  if (p.createdAfter) params.created_after = p.createdAfter
  if (p.createdBefore) params.created_before = p.createdBefore
  if (p.targetProfile) params.target_profile = p.targetProfile
  if (p.deviceSerial) params.device_serial = p.deviceSerial
  if (p.emptyResponseOnly) params.empty_response_only = true
  if (p.excludeEndSession) params.exclude_end_session = true
  if (p.durationAnomalyOnly) params.duration_anomaly_only = true
  // Repeated query params (?status=a&status=b) — axios's default params
  // serializer emits arrays this way, matching FastAPI's Query(list[...]).
  if (p.status?.length) params.status = p.status
  if (p.mode?.length) params.mode = p.mode
  return params
}

export function useBatches(params?: BatchQueryFilters) {
  const limit = params?.limit ?? 50
  const offset = params?.offset ?? 0
  const q = params?.q?.trim() || undefined
  const ca = params?.createdAfter ?? null
  const cb = params?.createdBefore ?? null
  const tp = params?.targetProfile ?? null
  const ds = params?.deviceSerial ?? null
  const eo = !!params?.emptyResponseOnly
  const xes = !!params?.excludeEndSession
  const dao = !!params?.durationAnomalyOnly
  const status = params?.status ?? null
  const mode = params?.mode ?? null
  return useQuery({
    queryKey: ['batches', limit, offset, q ?? null, ca, cb, tp, ds, eo, xes, dao, status, mode],
    queryFn: async () =>
      (
        await client.get<BatchSummary[]>('/batches', {
          params: buildBatchParams({
            limit,
            offset,
            q,
            createdAfter: params?.createdAfter,
            createdBefore: params?.createdBefore,
            targetProfile: params?.targetProfile,
            deviceSerial: params?.deviceSerial,
            emptyResponseOnly: eo,
            excludeEndSession: xes,
            durationAnomalyOnly: dao,
            status: params?.status,
            mode: params?.mode,
          }),
        })
      ).data,
    placeholderData: (prev) => prev,
    // Live progress: refetch every 2s while any row is still queued/running
    // so the list's done/failed/total column advances without opening detail;
    // idle otherwise to avoid pointless traffic.
    refetchInterval: (query) => {
      const rows = query.state.data
      const active = rows?.some((b) => b.status === 'queued' || b.status === 'running')
      return active ? 2000 : false
    },
  })
}

export interface BatchStats {
  total: number
  queued: number
  running: number
  done: number
  failed: number
  cancelled: number
}

export function useBatchStats(params?: {
  q?: string
  createdAfter?: string
  createdBefore?: string
  targetProfile?: string
  deviceSerial?: string
  emptyResponseOnly?: boolean
  excludeEndSession?: boolean
  durationAnomalyOnly?: boolean
  mode?: ExecutionMode[]
}) {
  const q = params?.q?.trim() || undefined
  const ca = params?.createdAfter ?? null
  const cb = params?.createdBefore ?? null
  const tp = params?.targetProfile ?? null
  const ds = params?.deviceSerial ?? null
  const eo = !!params?.emptyResponseOnly
  const xes = !!params?.excludeEndSession
  const dao = !!params?.durationAnomalyOnly
  const mode = params?.mode ?? null
  return useQuery({
    queryKey: ['batches', 'stats', q ?? null, ca, cb, tp, ds, eo, xes, dao, mode],
    queryFn: async () =>
      (
        await client.get<BatchStats>('/batches/stats', {
          params: buildBatchParams({
            q,
            createdAfter: params?.createdAfter,
            createdBefore: params?.createdBefore,
            targetProfile: params?.targetProfile,
            deviceSerial: params?.deviceSerial,
            emptyResponseOnly: eo,
            excludeEndSession: xes,
            durationAnomalyOnly: dao,
            mode: params?.mode,
          }),
        })
      ).data,
    // 2s while work is in flight (keeps the count chips in sync with the
    // list's live rows), 5s at rest.
    refetchInterval: (query) => {
      const s = query.state.data
      return s && (s.running > 0 || s.queued > 0) ? 2000 : 5000
    },
    placeholderData: (prev) => prev,
  })
}

export function useBatch(id: string | undefined) {
  return useQuery({
    queryKey: ['batch', id],
    queryFn: async () => (await client.get<BatchDetail>(`/batches/${id}`)).data,
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'queued' ? 2000 : false
    },
  })
}

// A session_id conversation is typically a sequence of separate
// single-sample batches (each turn its own submission), not one batch — so
// this is its own endpoint rather than something scoped to a batch_id.
export function useSessionConversation(sessionId: string | null) {
  return useQuery({
    queryKey: ['batches', 'sessions', sessionId],
    queryFn: async () =>
      (await client.get<SessionTurn[]>(`/batches/sessions/${encodeURIComponent(sessionId!)}`))
        .data,
    enabled: !!sessionId,
  })
}

export function useCreateBatchJson() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (body: BatchCreateJSON) =>
      (await client.post<BatchCreatedResponse>('/batches', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batches'] }),
  })
}

export function useUploadBatch() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (args: {
      name: string
      mode: ExecutionMode
      concurrency: number
      target_profile_default?: string
      file: File
    }) => {
      const formData = new FormData()
      formData.append('name', args.name)
      formData.append('mode', args.mode)
      formData.append('concurrency', String(args.concurrency))
      if (args.target_profile_default) {
        formData.append('target_profile_default', args.target_profile_default)
      }
      formData.append('file', args.file)

      const response = await client.post<BatchCreatedResponse>('/batches/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return response.data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batches'] }),
  })
}

export function useCancelBatch() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id: string) => {
      await client.post(`/batches/${id}/cancel`)
    },
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['batches'] })
      queryClient.invalidateQueries({ queryKey: ['batch', id] })
    },
  })
}

interface CancelActiveResponse {
  cancelled: number
  orphaned: number
  total: number
}

interface DeleteByStatusResponse {
  deleted: number
  matched: number
}

export function useDeleteBatch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await client.delete(`/batches/${id}`)
    },
    onSuccess: (_d, id) => {
      queryClient.invalidateQueries({ queryKey: ['batches'] })
      queryClient.invalidateQueries({ queryKey: ['batch-stats'] })
      queryClient.invalidateQueries({ queryKey: ['batch', id] })
    },
  })
}

export function useDeleteBatchesByStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (status: 'done' | 'failed' | 'cancelled' | 'terminal') => {
      const response = await client.post<DeleteByStatusResponse>(
        '/batches/delete-by-status',
        null,
        { params: { status } },
      )
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['batches'] })
      queryClient.invalidateQueries({ queryKey: ['batch-stats'] })
    },
  })
}

export function useCancelActiveBatches() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      const response = await client.post<CancelActiveResponse>('/batches/cancel-active')
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['batches'] })
      queryClient.invalidateQueries({ queryKey: ['batch-stats'] })
    },
  })
}

export function useRerunBatch() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (args: { id: string; status?: 'failed' | 'all' }) => {
      const response = await client.post<BatchCreatedResponse>(
        `/batches/${args.id}/rerun`,
        null,
        { params: { status: args.status ?? 'failed' } },
      )
      return response.data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batches'] }),
  })
}

/** Resubmits a batch with the exact original Sample list (new_session/
 * timeout_sec/retry/dry_run/callback_url included, not just prompts/mode/
 * target_profile like rerun). 400s if the batch predates replay support. */
export function useReplayBatch() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id: string) => {
      const response = await client.post<BatchCreatedResponse>(`/batches/${id}/replay`)
      return response.data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['batches'] }),
  })
}

export function statusIsTerminal(status: BatchStatus): boolean {
  return status === 'done' || status === 'failed' || status === 'cancelled'
}

/**
 * This route requires a bearer token, so it can't be a plain window.open —
 * browser navigations can't carry an Authorization header. Fetch through
 * the authenticated client as a blob and trigger the download client-side,
 * same as DownloadButton does for the batch-level results zip.
 */
export async function downloadSampleLogs(batchId: string, sampleId: string): Promise<void> {
  const response = await client.get(
    `/batches/${batchId}/samples/${encodeURIComponent(sampleId)}/logs.zip`,
    { responseType: 'blob' },
  )
  const filename =
    parseContentDisposition(response.headers['content-disposition']) ?? `${sampleId}.zip`
  triggerDownload(response.data as Blob, filename)
}
