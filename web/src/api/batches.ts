import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BatchCreatedResponse,
  BatchCreateJSON,
  BatchDetail,
  BatchStatus,
  BatchSummary,
} from '../types/api'
import { client } from './client'

export function useBatches() {
  return useQuery({
    queryKey: ['batches'],
    queryFn: async () => (await client.get<BatchSummary[]>('/batches')).data,
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
      mode: 'api'
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
