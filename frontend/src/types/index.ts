export interface User {
  id: number
  username: string
  email: string
  role: "admin" | "user"
  created_at: string
}

export interface UserStats {
  user_id: number
  username: string
  email: string
  role: "admin" | "user"
  audio_file_count: number
  transcription_count: number
  running_job_count: number
  web_audio_count: number
  telegram_audio_count: number
}

export interface Project {
  id: number
  name: string
  description: string | null
  created_at: string
  updated_at: string | null
}

export interface AudioFile {
  id: number
  project_id: number | null
  project: Project | null
  original_filename: string
  display_name: string | null
  notes: string | null
  source: string | null
  mime_type: string | null
  size_bytes: number
  duration_seconds: number | null
  created_at: string
}

export interface TranscriptionModel {
  id: number
  provider: string
  variant: string
  display_name: string
  language_mode: "english" | "multilingual" | "russian"
  download_url: string | null
  status: "installing" | "installed" | "failed"
  size_bytes: number | null
  downloaded_bytes: number
  total_bytes: number | null
  status_text: string | null
  error_message: string | null
  installed_at: string | null
  created_at: string
}

export interface ModelStats {
  model_id: number
  worker_id: number | null
  worker_name: string | null
  completed_job_count: number
  total_audio_seconds: number
  total_runtime_seconds: number
  runtime_per_audio_hour_seconds: number
  median_runtime_per_audio_hour_seconds: number | null
  last_completed_at: string | null
}

export interface ModelCatalogItem {
  provider: string
  variant: string
  display_name: string
  language_mode: "english" | "multilingual" | "russian"
  disk_hint: string
  ram_hint: string
  download_url: string
  model_variant: string | null
}

export interface WhisperCliSettings {
  whisper_threads: number
  whisper_max_context: number
  whisper_use_gpu: boolean
  whisper_flash_attn: boolean
  whisper_suppress_non_speech: boolean
  whisper_suppress_regex: string | null
  transcript_filter_regex: string | null
}

export interface WhisperCliSettingsResponse extends WhisperCliSettings {
  defaults: WhisperCliSettings
  cli_preview: string[]
}

export interface TelegramAllowedUser {
  telegram_user_id: number
  app_user_id: number
  preferred_worker_id: number | null
  preferred_model_id: number | null
  split_enabled: boolean | null
  split_worker_ids: number[]
}

export interface TelegramBotStatus {
  running: boolean
  enabled: boolean
  token_configured: boolean
  token_preview: string | null
  last_poll_at: string | null
  last_error: string | null
  update_offset: number | null
}

export interface TelegramBotSettingsResponse {
  enabled: boolean
  proxy_url: string | null
  default_model_id: number | null
  default_language: string
  split_enabled: boolean
  split_worker_ids: number[]
  allowed_users: TelegramAllowedUser[]
  token_configured: boolean
  token_preview: string | null
  status: TelegramBotStatus
}

export interface TelegramBotTestResponse {
  ok: boolean
  username: string | null
  first_name: string | null
  error: string | null
}

export interface CleanupSettingsResponse {
  failed_cancelled_retention_days: number
  deleted_count_last_run: number
}

export interface TranscriptionJob {
  id: number
  owner_user_id: number
  audio_file_id: number
  model_id: number
  language: string
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled"
  status_text: string | null
  error_message: string | null
  transcript_text: string | null
  output_txt_size_bytes: number | null
  output_json_size_bytes: number | null
  output_srt_size_bytes: number | null
  output_vtt_size_bytes: number | null
  partial_transcript_text: string | null
  partial_transcript_json: string | null
  partial_updated_at: string | null
  source: string | null
  telegram_chat_id: string | null
  telegram_user_id: string | null
  telegram_message_id: string | null
  telegram_file_id: string | null
  telegram_result_sent_at: string | null
  telegram_result_error: string | null
  worker_id: number | null
  worker_name_snapshot: string | null
  preferred_worker_id: number | null
  preferred_worker_name_snapshot: string | null
  split_worker_ids: number[]
  claimed_at: string | null
  worker_heartbeat_at: string | null
  cancel_requested_at: string | null
  split_enabled: boolean
  split_status: string | null
  split_chunk_count: number
  split_chunks_completed: number
  split_chunks_running: number
  split_chunks_queued: number
  split_chunks_failed: number
  running_worker_names: string[]
  split_chunks: TranscriptionJobChunk[]
  created_at: string
  started_at: string | null
  finished_at: string | null
  audio_file: AudioFile | null
  model: TranscriptionModel | null
}

export interface TranscriptionJobChunk {
  id: number
  index: number
  start_seconds: number
  end_seconds: number
  overlap_start_seconds: number
  overlap_end_seconds: number
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled"
  status_text: string | null
  error_message: string | null
  worker_id: number | null
  worker_name_snapshot: string | null
  claimed_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface WorkerModelState {
  variant: string
  status: string
  path: string | null
  downloaded_bytes: number
  total_bytes: number | null
  error_message: string | null
}

export interface WorkerModelSpeedStat {
  variant: string
  completed_count: number
  total_runtime_seconds: number
  total_audio_seconds: number
  runtime_per_audio_hour_seconds: number | null
}

export interface TranscriptionWorker {
  id: number
  name: string
  display_name: string | null
  accepted: boolean
  is_deleted: boolean
  status: string
  online: boolean
  last_heartbeat_at: string | null
  current_job_count: number
  completed_job_count: number
  failed_job_count: number
  cancelled_job_count: number
  total_runtime_seconds: number
  total_audio_seconds: number
  model_speed_stats: WorkerModelSpeedStat[]
  models: WorkerModelState[]
  installs: WorkerModelState[]
  requested_installs: string[]
  requested_uninstalls: string[]
  last_error: string | null
  auto_install_models: boolean
  created_at: string
  updated_at: string | null
}
