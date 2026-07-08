import { useMutation } from '@tanstack/react-query'

import {
  ProfileBuilderDraftResponse,
  ProfileBuilderReviewResponse,
  ProfileBuilderSessionCreate,
  ProfileBuilderValidateResponse,
  ProfileBuilderSessionView,
} from '../types/api'

interface NewSessionConfigArgs {
  sessionId: string
  strategy: 'disabled' | 'guided_tap_sequence'
  stepCount: number
}

interface NewSessionStepCaptureArgs {
  sessionId: string
  stepIndex: number
}

interface NewSessionStepConfirmArgs {
  sessionId: string
  stepIndex: number
  x: number
  y: number
  source: 'recommended' | 'manual'
}
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

export interface BuilderAdvancedOptions {
  complete_detection?: Record<string, unknown> | null
  method?: 'ui_tree_only' | 'ocr_only' | 'ui_tree_then_ocr' | null
  copy_button_vlm?: Record<string, unknown> | null
  response_vlm?: Record<string, unknown> | null
  init_action?: Array<Record<string, unknown>> | null
  init_reboot?: boolean | null
}

export function useGenerateProfileBuilderDraft() {
  return useMutation({
    mutationFn: async (args: {
      sessionId: string
      draftMode: 'rule' | 'smart'
      injectLlm?: boolean
      advanced?: BuilderAdvancedOptions
    }) =>
      (
        await client.post<ProfileBuilderDraftResponse>(
          `/profile-builder/sessions/${args.sessionId}/draft`,
          {
            draft_mode: args.draftMode,
            inject_llm: !!args.injectLlm,
            ...(args.advanced ? { advanced: args.advanced } : {}),
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

export function useConfigureProfileBuilderNewSession() {
  return useMutation({
    mutationFn: async ({ sessionId, strategy, stepCount }: NewSessionConfigArgs) =>
      (
        await client.put<ProfileBuilderDraftResponse>(
          `/profile-builder/sessions/${sessionId}/new-session/config`,
          { strategy, step_count: stepCount },
        )
      ).data,
  })
}

export function useCaptureProfileBuilderNewSessionStep() {
  return useMutation({
    mutationFn: async ({ sessionId, stepIndex }: NewSessionStepCaptureArgs) =>
      (
        await client.post<ProfileBuilderDraftResponse>(
          `/profile-builder/sessions/${sessionId}/new-session/step/${stepIndex}/capture`,
        )
      ).data,
  })
}

export function useConfirmProfileBuilderNewSessionStep() {
  return useMutation({
    mutationFn: async ({ sessionId, stepIndex, x, y, source }: NewSessionStepConfirmArgs) =>
      (
        await client.put<ProfileBuilderDraftResponse>(
          `/profile-builder/sessions/${sessionId}/new-session/step/${stepIndex}/confirm`,
          { x, y, source },
        )
      ).data,
  })
}
