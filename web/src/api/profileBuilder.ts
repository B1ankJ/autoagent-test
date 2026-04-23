import { useMutation } from '@tanstack/react-query'

import {
  ProfileBuilderDraftResponse,
  ProfileBuilderSessionCreate,
  ProfileBuilderSessionView,
} from '../types/api'
import { client } from './client'

export function useCreateProfileBuilderSession() {
  return useMutation({
    mutationFn: async (payload: ProfileBuilderSessionCreate) =>
      (await client.post<ProfileBuilderSessionView>('/profile-builder/sessions', payload)).data,
  })
}

export function useCaptureProfileBuilderStep() {
  return useMutation({
    mutationFn: async (args: { sessionId: string; step: string }) =>
      (
        await client.post<ProfileBuilderSessionView>(
          `/profile-builder/sessions/${args.sessionId}/capture/${args.step}`,
        )
      ).data,
  })
}

export function useGenerateProfileBuilderDraft() {
  return useMutation({
    mutationFn: async (sessionId: string) =>
      (
        await client.post<ProfileBuilderDraftResponse>(
          `/profile-builder/sessions/${sessionId}/draft`,
        )
      ).data,
  })
}
