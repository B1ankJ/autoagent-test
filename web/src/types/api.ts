export type ExecutionMode = 'api' | 'gui_pc_web' | 'gui_android'
export type ProfilePlatform = 'api' | 'web' | 'android'
export type SampleStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'timeout'
  | 'extraction_failed'
  | 'cancelled'
export type BatchStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  expires_in_sec: number
}

export interface Sample {
  id: string
  prompts: string[]
  mode: ExecutionMode
  target_profile: string
  new_session?: boolean
  timeout_sec?: number
  retry?: number
  dry_run?: boolean
  metadata?: Record<string, unknown>
  status?: SampleStatus
  responses?: string[]
  duration_ms?: number
  error?: string
  logs_dir?: string
  attempt_count?: number
  prompts_sent?: string[]
  llm_responses?: string[]
  llm_errors?: Array<string | null>
  started_at?: string
  ended_at?: string
  device_serial?: string | null
  waiting_for_device?: boolean
}

export interface BatchSummary {
  batch_id: string
  name: string
  mode: ExecutionMode
  status: BatchStatus
  total: number
  done: number
  failed: number
  avg_duration_ms?: number
  total_duration_ms?: number
  started_at?: string
  ended_at?: string
}

export interface BatchDetail extends BatchSummary {
  concurrency: number
  target_profile_default?: string
  samples: Sample[]
  seq: number
}

export interface SampleUpdate {
  sample_id: string
  status: SampleStatus
  device_serial?: string | null
  waiting_for_device?: boolean
}

export interface BatchCreateJSON {
  name: string
  mode: ExecutionMode
  concurrency?: number
  target_profile_default?: string
  webhook_url?: string
  samples: Sample[]
}

export interface BatchCreatedResponse {
  batch_id: string
}

export interface ProfileSummary {
  name: string
  platform: ProfilePlatform
}

export interface Device {
  serial: string
  label: string | null
  model: string | null
  android_version: string | null
  adb_keyboard_installed: boolean | null
  adb_keyboard_enabled: boolean | null
  online: boolean
  enabled: boolean
  last_seen_at: string | null
}

export interface ValidateResponse {
  ok: boolean
  error?: string
}

export interface SingleTestSyncResponse {
  id: string
  status: SampleStatus
  responses: string[]
  llm_responses?: string[]
  llm_errors?: Array<string | null>
  duration_ms?: number
  error?: string
}

export interface SingleTestAsyncCreated {
  task_id: string
  status: 'queued'
}

export type SingleTestAsyncStatus = SingleTestSyncResponse

export interface ScreenshotInfo {
  name: string
  label: string
  taken_at: string
  is_sensitive?: boolean | null
}

export interface VLMConfig {
  base_url: string
  model: string
  api_key: string | null
  extra_headers?: Record<string, string>
}

export interface GlobalDefaults {
  api_timeout_sec?: number
  gui_timeout_sec?: number
  retry?: number
  concurrency?: number
  verbose_logs?: boolean
}

export interface ProfileBuilderCaptureArtifact {
  step: string
  package: string
  activity: string | null
  xml_artifact: string
  screenshot_artifact: string
  active: boolean
  captured_at: string | null
}

export interface ProfileBuilderSessionCreate {
  platform: 'android'
  device_serial: string
  name: string
}

export interface LocatorChoice {
  type: string
  value: string
}

export interface ResponseReviewOption {
  response_container_locator: LocatorChoice
  scroll_container_locator: LocatorChoice
  latest_bubble_match: LocatorChoice
  resolved_latest_bubble_match?: LocatorChoice
  bubble_preview?: string
}

export interface ActionStepChoice {
  action: string
  x?: number
  y?: number
  locator?: LocatorChoice
}

export type ActionStepsReviewOption = ActionStepChoice[]

export interface ReviewEvidenceRef {
  source: string
  step: string
  artifact: string
  locator?: LocatorChoice
  bounds?: [number, number, number, number] | number[]
  label?: string
  text?: string
  scroll_locator?: LocatorChoice
  text_count?: number
  total_text_length?: number
}

export interface ReviewItem {
  field: string
  reason: string
  recommended_option: LocatorChoice | ResponseReviewOption | ActionStepsReviewOption
  alternative_candidates: Array<LocatorChoice | ResponseReviewOption | ActionStepsReviewOption>
  evidence_refs: ReviewEvidenceRef[]
  alternative_evidence_refs: ReviewEvidenceRef[][]
}

export interface CandidateOption {
  locator?: LocatorChoice
  response_container_locator?: LocatorChoice
  scroll_container_locator?: LocatorChoice
  latest_bubble_match?: LocatorChoice
  score: number
  reason: string
  evidence_refs: ReviewEvidenceRef[]
}

export interface ProfileBuilderCandidates {
  input_candidates: CandidateOption[]
  send_candidates: CandidateOption[]
  response_candidates: CandidateOption[]
  review_items: ReviewItem[]
}

export interface ProfileBuilderSessionView {
  id: string
  platform: 'android'
  device_serial: string
  name: string
  status: 'draft' | 'ready' | 'validated'
  steps: string[]
  artifact_dir: string
  artifacts: string[]
  captures: ProfileBuilderCaptureArtifact[]
}

export interface ProfileBuilderRuntimeScreen {
  step: string
  label: string
  path: string
  taken_at: string
}

export interface ProfileBuilderRuntimeCapture {
  step: string
  status: 'pending' | 'running' | 'done' | 'failed'
  screenshot: string | null
  updated_at: string | null
}

export interface ProfileBuilderRuntimeConnectivity {
  status: 'idle' | 'running' | 'done' | 'failed'
  result_status: SampleStatus | null
  result_summary: string | null
  screens: ProfileBuilderRuntimeScreen[]
}

export interface ProfileBuilderRuntimeView {
  session_id: string
  session_status: 'draft' | 'ready' | 'validating' | 'validated' | 'failed'
  current_step: string
  step_state: 'idle' | 'running' | 'done' | 'failed'
  last_error: string | null
  builder_adb_keyboard_active: boolean
  builder_previous_ime: string | null
  captures: ProfileBuilderRuntimeCapture[]
  connectivity: ProfileBuilderRuntimeConnectivity
  recent_screens: ProfileBuilderRuntimeScreen[]
}

export interface ProfileBuilderTapPoint {
  x: number
  y: number
}

export interface ProfileBuilderNewSessionRecommendation {
  point: ProfileBuilderTapPoint | null
  reason: string | null
  status: 'idle' | 'ready' | 'failed'
}

export interface ProfileBuilderNewSessionStep {
  step_index: number
  xml_artifact: string | null
  screenshot_artifact: string | null
  recommended_tap: ProfileBuilderNewSessionRecommendation
  confirmed_tap: ProfileBuilderTapPoint | null
  source: 'recommended' | 'manual' | null
}

export interface ProfileBuilderDraftResponse {
  session: ProfileBuilderSessionView
  candidates: ProfileBuilderCandidates
  review_items: ReviewItem[]
  draft_profile_yaml: string
  draft_mode: 'rule' | 'smart'
  requires_manual_review: boolean
  applied_review_choices: Record<string, number>
  pending_review_fields: string[]
  auto_review_source: 'manual' | 'llm'
  new_session_strategy: 'disabled' | 'guided_tap_sequence'
  new_session_steps: ProfileBuilderNewSessionStep[]
}

export interface ProfileBuilderReviewResponse {
  session: ProfileBuilderSessionView
  draft_profile_yaml: string
}

export interface ProfileBuilderValidateResponse {
  session: ProfileBuilderSessionView
  draft_profile_yaml: string
  connectivity_result: SingleTestSyncResponse
}
