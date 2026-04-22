import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Sample,
  SingleTestAsyncCreated,
  SingleTestAsyncStatus,
  SingleTestSyncResponse,
} from '../types/api'
import { client } from './client'

export function useRunSync() {
  return useMutation({
    mutationFn: async (sample: Sample) =>
      (await client.post<SingleTestSyncResponse>('/tests/sync', sample)).data,
  })
}

export function useRunAsync() {
  return useMutation({
    mutationFn: async (sample: Sample) =>
      (await client.post<SingleTestAsyncCreated>('/tests', sample)).data,
  })
}

export function useAsyncResult(taskId: string | undefined) {
  return useQuery({
    queryKey: ['test', taskId],
    queryFn: async () => (await client.get<SingleTestAsyncStatus>(`/tests/${taskId}`)).data,
    enabled: !!taskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'pending' || !status ? 1000 : false
    },
  })
}
