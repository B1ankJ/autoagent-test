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
