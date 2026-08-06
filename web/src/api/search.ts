import { useQuery } from '@tanstack/react-query'
import { SampleSearchResponse } from '../types/api'
import { client } from './client'

export interface SampleSearchParams {
  q: string
  targetProfile?: string
  fields?: string
  status?: string[]
  createdAfter?: string
  createdBefore?: string
  page: number
  pageSize?: number
}

export function buildSearchParams(
  p: SampleSearchParams,
): Record<string, string | number | string[]> {
  const pageSize = p.pageSize ?? 20
  const out: Record<string, string | number | string[]> = {
    q: p.q.trim(),
    limit: pageSize,
    offset: (p.page - 1) * pageSize,
  }
  if (p.targetProfile) out.target_profile = p.targetProfile
  if (p.fields && p.fields !== 'all') out.fields = p.fields
  if (p.status && p.status.length) out.status = p.status
  if (p.createdAfter) out.created_after = p.createdAfter
  if (p.createdBefore) out.created_before = p.createdBefore
  return out
}

export function useSampleSearch(params: SampleSearchParams) {
  const trimmed = params.q.trim()
  return useQuery({
    queryKey: ['samples', 'search', buildSearchParams(params)],
    enabled: trimmed.length >= 2,
    queryFn: async () =>
      (
        await client.get<SampleSearchResponse>('/samples/search', {
          params: buildSearchParams(params),
        })
      ).data,
  })
}
