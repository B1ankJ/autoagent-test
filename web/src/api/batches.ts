import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BatchCreatedResponse,
  BatchCreateJSON,
  BatchDetail,
  ExecutionMode,
  BatchStatus,
  BatchSummary,
} from '../types/api'
import { client } from './client'
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
}

function buildBatchParams(p: BatchQueryFilters) {
  const params: Record<string, string | number | boolean> = {}
  if (p.limit !== undefined) params.limit = p.limit
  if (p.offset !== undefined) params.offset = p.offset
  const q = p.q?.trim()
  if (q) params.q = q
  if (p.createdAfter) params.created_after = p.createdAfter
  if (p.createdBefore) params.created_before = p.createdBefore
  if (p.targetProfile) params.target_profile = p.targetProfile
  if (p.deviceSerial) params.device_serial = p.deviceSerial
  if (p.emptyResponseOnly) params.empty_response_only = true
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
  return useQuery({
    queryKey: ['batches', limit, offset, q ?? null, ca, cb, tp, ds, eo],
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
          }),
        })
      ).data,
    placeholderData: (prev) => prev,
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
}) {
  const q = params?.q?.trim() || undefined
  const ca = params?.createdAfter ?? null
  const cb = params?.createdBefore ?? null
  const tp = params?.targetProfile ?? null
  const ds = params?.deviceSerial ?? null
  const eo = !!params?.emptyResponseOnly
  return useQuery({
    queryKey: ['batches', 'stats', q ?? null, ca, cb, tp, ds, eo],
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
          }),
        })
      ).data,
    refetchInterval: 5000,
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

export function statusIsTerminal(status: BatchStatus): boolean {
  return status === 'done' || status === 'failed' || status === 'cancelled'
}

export function downloadSampleLogs(batchId: string, sampleId: string) {
  window.open(
    `/api/v1/batches/${batchId}/samples/${encodeURIComponent(sampleId)}/logs.zip`,
    '_blank',
    'noopener,noreferrer',
  )
}
