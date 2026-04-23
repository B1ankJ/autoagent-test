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
  api_key_env: string
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
}

export interface ReviewItem {
  field: string
  reason: string
  recommended_option: LocatorChoice | ResponseReviewOption
  alternative_candidates: Array<LocatorChoice | ResponseReviewOption>
  evidence_refs: Record<string, unknown>[]
}

export interface CandidateOption {
  locator?: LocatorChoice
  response_container_locator?: LocatorChoice
  scroll_container_locator?: LocatorChoice
  latest_bubble_match?: LocatorChoice
  score: number
  reason: string
  evidence_refs: Record<string, unknown>[]
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

export interface ProfileBuilderDraftResponse {
  session: ProfileBuilderSessionView
  candidates: ProfileBuilderCandidates
  review_items: ReviewItem[]
  draft_profile_yaml: string
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
