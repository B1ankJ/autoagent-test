import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { client } from './client'

export interface SessionView {
  id: string
  url: string
  selections: Record<
    string,
    { selector: string; info: Record<string, unknown>; send_type?: string; keyboard_key?: string }
  >
}

export interface PickResult {
  field: string
  selector: string
  element_info: Record<string, unknown>
}

export function useCreateWebBuilderSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: {
      url: string
      channel?: string
      headless?: boolean
      user_data_dir?: string | null
    }) => (await client.post<SessionView>('/web-profile-builder/sessions', body)).data,
    onSuccess: (data) => {
      qc.setQueryData(['web-builder-session', data.id], data)
    },
  })
}

export function useWebBuilderSession(sessionId: string | null) {
  return useQuery({
    queryKey: ['web-builder-session', sessionId],
    queryFn: async () =>
      (await client.get<SessionView>(`/web-profile-builder/sessions/${sessionId}`)).data,
    enabled: !!sessionId,
    refetchOnWindowFocus: false,
  })
}

export function useWebBuilderScreenshot(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['web-builder-screenshot', sessionId],
    queryFn: async () =>
      (
        await client.get<{ image: string }>(
          `/web-profile-builder/sessions/${sessionId}/screenshot`,
        )
      ).data,
    enabled: !!sessionId && enabled,
    refetchOnWindowFocus: false,
    staleTime: 0,
    gcTime: 0,
  })
}

export function usePickElement(sessionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: {
      field: string
      x: number
      y: number
      send_type?: string
      keyboard_key?: string
    }) =>
      (
        await client.post<PickResult>(
          `/web-profile-builder/sessions/${sessionId}/pick`,
          body,
        )
      ).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['web-builder-session', sessionId] })
      qc.invalidateQueries({ queryKey: ['web-builder-screenshot', sessionId] })
    },
  })
}

export function useClearSelection(sessionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (field: string) =>
      (
        await client.delete(
          `/web-profile-builder/sessions/${sessionId}/selections/${field}`,
        )
      ).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['web-builder-session', sessionId] })
    },
  })
}

export function useGenerateWebProfile(sessionId: string) {
  return useMutation({
    mutationFn: async (body: {
      name: string
      profile_url?: string
      stable_sec?: number
      ready_timeout_sec?: number
      inject_llm?: boolean
    }) =>
      (
        await client.post<{ yaml: string }>(
          `/web-profile-builder/sessions/${sessionId}/generate`,
          body,
        )
      ).data,
  })
}

export function useCloseWebBuilderSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) =>
      (await client.delete(`/web-profile-builder/sessions/${sessionId}`)).data,
    onSuccess: (_data, sessionId) => {
      qc.removeQueries({ queryKey: ['web-builder-session', sessionId] })
      qc.removeQueries({ queryKey: ['web-builder-screenshot', sessionId] })
    },
  })
}
