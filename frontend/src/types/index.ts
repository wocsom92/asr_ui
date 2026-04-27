export interface User {
  id: number
  username: string
  email: string
  role: "admin" | "user"
  created_at: string
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
  created_at: string
  started_at: string | null
  finished_at: string | null
  audio_file: AudioFile | null
  model: TranscriptionModel | null
}
