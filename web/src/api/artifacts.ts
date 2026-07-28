import { useQuery } from '@tanstack/react-query'
import { client } from './client'

/** Names of plain-text artifacts (executor.log, after_result_*.xml, ...)
 * available for on-demand inline viewing in SampleDetail — separate from
 * screenshots (media.py) and the full logs.zip download. */
export function useSampleArtifactList(batchId: string, sampleId: string, enabled = true) {
  return useQuery({
    queryKey: ['sample-artifacts', batchId, sampleId],
    queryFn: async () =>
      (await client.get<string[]>(`/batches/${batchId}/samples/${sampleId}/artifacts`)).data,
    enabled: enabled && !!batchId && !!sampleId,
  })
}

/** Fetches one artifact's raw text content. Pass `enabled=false` until the
 * user actually expands it — these can be large and shouldn't be fetched
 * just because the sample page loaded. */
export function useSampleArtifactContent(
  batchId: string,
  sampleId: string,
  name: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['sample-artifact-content', batchId, sampleId, name],
    queryFn: async () =>
      (
        await client.get<string>(
          `/batches/${batchId}/samples/${sampleId}/artifact/${encodeURIComponent(name)}`,
          { responseType: 'text' },
        )
      ).data,
    enabled,
  })
}
