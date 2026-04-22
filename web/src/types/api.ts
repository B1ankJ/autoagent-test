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
