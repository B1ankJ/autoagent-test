import { useQuery } from '@tanstack/react-query'

import { ProfileBuilderRuntimeView } from '../types/api'
import { client } from './client'

export async function fetchProfileBuilderRuntime(
  sessionId: string,
): Promise<ProfileBuilderRuntimeView> {
  const response = await client.get<ProfileBuilderRuntimeView>(
    `/profile-builder/sessions/${sessionId}/runtime`,
  )
  return response.data
}

export async function fetchProfileBuilderArtifactBlobUrl(
  sessionId: string,
  name: string,
): Promise<string> {
  const response = await client.get<Blob>(
    `/profile-builder/sessions/${sessionId}/artifacts/${encodeURIComponent(name)}`,
    { responseType: 'blob' },
  )
  if (typeof URL.createObjectURL !== 'function') {
    throw new Error('blob preview is not supported in this environment')
  }
  return URL.createObjectURL(response.data)
}

export function useProfileBuilderRuntime(sessionId?: string) {
  return useQuery({
    queryKey: ['profile-builder-runtime', sessionId],
    queryFn: () => fetchProfileBuilderRuntime(sessionId!),
    enabled: Boolean(sessionId),
    refetchInterval: (query) => {
      const runtime = query.state.data
      if (!runtime) {
        return 1500
      }
      if (runtime.step_state === 'running' || runtime.session_status === 'validating') {
        return 1500
      }
      return 4000
    },
  })
}
