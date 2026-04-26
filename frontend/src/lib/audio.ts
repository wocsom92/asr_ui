import type { AudioFile } from "@/types"

export function audioTitle(file: AudioFile | null | undefined, fallback = "Audio"): string {
  return file?.display_name || file?.original_filename || fallback
}
