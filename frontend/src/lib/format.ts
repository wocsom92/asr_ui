export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "0 B"
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), sizes.length - 1)
  return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${sizes[index]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "Unknown"
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remaining = total % 60
  if (hours > 0) return `${hours}h ${minutes}m ${remaining}s`
  return minutes > 0 ? `${minutes}m ${remaining}s` : `${remaining}s`
}

export function formatElapsedMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms) || ms < 0) return "Unknown"
  if (ms < 1000) return `${Math.round(ms)}ms`
  const total = Math.round(ms / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remaining = total % 60
  if (hours > 0) return `${hours}h ${minutes}m ${remaining}s`
  return minutes > 0 ? `${minutes}m ${remaining}s` : `${remaining}s`
}
