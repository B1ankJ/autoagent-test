export type Mode = 'api' | 'web' | 'android'
export type SampleStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
export type BatchStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  expires_at: string
}

export interface Sample {
  id: string
  prompts: string[]
  mode: Mode
  target_profile: string
  new_session?: boolean
  metadata?: Record<string, unknown>
  status?: SampleStatus
  responses?: string[]
  duration_ms?: number
  error?: string
  started_at?: string
  finished_at?: string
}

export interface BatchSummary {
  id: string
  name: string
  mode: Mode
  status: BatchStatus
  total: number
  done: number
  failed: number
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface BatchDetail extends BatchSummary {
  concurrency: number
  target_profile_default?: string
  webhook_url?: string
  samples: Sample[]
}

export interface BatchCreateJSON {
  name: string
  mode: Mode
  concurrency?: number
  target_profile_default?: string
  webhook_url?: string
  samples: Sample[]
}

export interface BatchCreatedResponse {
  id: string
}

export interface ProfileSummary {
  name: string
  platform: 'api' | 'web' | 'android'
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
}

export interface SingleTestAsyncStatus {
  task_id: string
  status: SampleStatus
  result?: SingleTestSyncResponse
}

export interface VLMConfig {
  base_url: string
  model: string
  api_key_env: string
}

export interface GlobalDefaults {
  api_timeout_sec?: number
  gui_timeout_sec?: number
  retry?: number
  verbose_logs?: boolean
  [key: string]: unknown
}
