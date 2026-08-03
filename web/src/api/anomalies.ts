import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnomalyListResponse, AnomalyType } from '../types/api'
import { client } from './client'

export interface AnomalyFilters {
  type?: AnomalyType
  target_profile?: string
  acknowledged?: boolean
  limit: number
  offset: number
}

export function buildAnomalyParams(f: AnomalyFilters): Record<string, string | number | boolean> {
  const p: Record<string, string | number | boolean> = { limit: f.limit, offset: f.offset }
  if (f.type) p.type = f.type
  if (f.target_profile) p.target_profile = f.target_profile
  if (f.acknowledged !== undefined) p.acknowledged = f.acknowledged
  return p
}

export function useAnomalies(filters: AnomalyFilters) {
  return useQuery({
    queryKey: ['anomalies', filters],
    queryFn: async () =>
      (
        await client.get<AnomalyListResponse>('/anomalies', {
          params: buildAnomalyParams(filters),
        })
      ).data,
  })
}

export function useAnomalyCount() {
  return useQuery({
    queryKey: ['anomalies', 'count'],
    queryFn: async () =>
      (
        await client.get<{ count: number }>('/anomalies/count', {
          params: { acknowledged: false },
        })
      ).data.count,
    refetchInterval: 30000,
  })
}

export function useAcknowledgeAnomaly() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => (await client.post(`/anomalies/${id}/acknowledge`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['anomalies'] })
    },
  })
}
