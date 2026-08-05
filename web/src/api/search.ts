import { useQuery } from '@tanstack/react-query'
import { SampleSearchResponse } from '../types/api'
import { client } from './client'

export interface SampleSearchParams {
  q: string
  targetProfile?: string
  page: number
  pageSize?: number
}

export function useSampleSearch({ q, targetProfile, page, pageSize = 20 }: SampleSearchParams) {
  const trimmed = q.trim()
  return useQuery({
    queryKey: ['samples', 'search', trimmed, targetProfile, page, pageSize],
    enabled: trimmed.length >= 2,
    queryFn: async () =>
      (
        await client.get<SampleSearchResponse>('/samples/search', {
          params: {
            q: trimmed,
            target_profile: targetProfile || undefined,
            limit: pageSize,
            offset: (page - 1) * pageSize,
          },
        })
      ).data,
  })
}
