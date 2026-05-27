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

export function useBatches(params?: { limit?: number; offset?: number }) {
  const limit = params?.limit ?? 50
  const offset = params?.offset ?? 0
  return useQuery({
    queryKey: ['batches', limit, offset],
    queryFn: async () =>
      (
        await client.get<BatchSummary[]>('/batches', {
          params: { limit, offset },
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

export function useBatchStats() {
  return useQuery({
    queryKey: ['batches', 'stats'],
    queryFn: async () => (await client.get<BatchStats>('/batches/stats')).data,
    refetchInterval: 5000,
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

export function statusIsTerminal(status: BatchStatus): boolean {
  return status === 'done' || status === 'failed' || status === 'cancelled'
}

export function downloadSampleActions(batchId: string, sampleId: string) {
  window.open(
    `/api/v1/batches/${batchId}/samples/${encodeURIComponent(sampleId)}/actions.jsonl`,
    '_blank',
    'noopener,noreferrer',
  )
}
