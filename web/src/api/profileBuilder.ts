import { useMutation } from '@tanstack/react-query'

import {
  ProfileBuilderDraftResponse,
  ProfileBuilderReviewResponse,
  ProfileBuilderSessionCreate,
  ProfileBuilderValidateResponse,
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
    mutationFn: async (args: { sessionId: string; useLlmOptimization?: boolean; injectLlm?: boolean }) =>
      (
        await client.post<ProfileBuilderDraftResponse>(
          `/profile-builder/sessions/${args.sessionId}/draft`,
          {
            use_llm_optimization: args.useLlmOptimization ?? true,
            inject_llm: !!args.injectLlm,
          },
        )
      ).data,
  })
}

export function useApplyProfileBuilderReview() {
  return useMutation({
    mutationFn: async (args: { sessionId: string; payload: Record<string, unknown> }) =>
      (
        await client.post<ProfileBuilderReviewResponse>(
          `/profile-builder/sessions/${args.sessionId}/review`,
          args.payload,
        )
      ).data,
  })
}

export function useValidateProfileBuilderDraft() {
  return useMutation({
    mutationFn: async (sessionId: string) =>
      (
        await client.post<ProfileBuilderValidateResponse>(
          `/profile-builder/sessions/${sessionId}/validate`,
        )
      ).data,
  })
}
