import type { ReactNode } from "react"
import { Ban, CheckCircle2, Clock3, Loader2, XCircle } from "lucide-react"
import type { TranscriptionJob } from "@/types"
import { parseApiDate } from "@/lib/datetime"
import { formatElapsedMs } from "@/lib/format"

/** Running job after user requested cancel (API sets status_text before worker finishes). */
export function isJobCancelling(job: TranscriptionJob | null | undefined): boolean {
  if (!job || job.status !== "running") return false
  const t = (job.status_text ?? "").toLowerCase()
  return t.includes("cancelling") || t.includes("canceling")
}

export function statusIcon(job: TranscriptionJob) {
  const { status } = job
  if (status === "succeeded") return <CheckCircle2 className="h-4 w-4 text-green-600" />
  if (status === "failed") return <XCircle className="h-4 w-4 text-destructive" />
  if (status === "cancelled") return <Ban className="h-4 w-4 text-muted-foreground" />
  if (isJobCancelling(job)) {
    return <Loader2 className="h-4 w-4 animate-spin text-blue-600" aria-label="Cancelling" />
  }
  if (status === "queued") return <Clock3 className="h-4 w-4 text-sky-500" />
  return <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
}

/** Badge label: show intermediate state while worker stops whisper/ffmpeg. */
export function jobStatusLabel(job: TranscriptionJob): string {
  if (isJobCancelling(job)) return "cancelling"
  return job.status
}

export function jobStatusBadgeClass(job: TranscriptionJob): string {
  if (job.status === "succeeded") return "border-green-600/25 bg-green-600 text-white hover:bg-green-700"
  if (job.status === "running") return "border-blue-600/25 bg-blue-600 text-white hover:bg-blue-700"
  if (job.status === "failed") return "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80"
  if (job.status === "cancelled") return "border-gray-300 bg-gray-200 text-gray-800 hover:bg-gray-300 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
  return "border-sky-200 bg-sky-100 text-sky-900 hover:bg-sky-200 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-200 dark:hover:bg-sky-900"
}

export function jobRuntime(job: TranscriptionJob): string {
  if (!job.started_at) return "Not started"
  const end = job.finished_at ? parseApiDate(job.finished_at) : new Date()
  return formatElapsedMs(end.getTime() - parseApiDate(job.started_at).getTime())
}

export function jobProgress(job: TranscriptionJob | null | undefined): number | null {
  if (!job || job.status !== "running") return null
  const match = (job.status_text ?? "").match(/(\d{1,3})%/)
  if (!match) return null
  const value = Number(match[1])
  if (!Number.isFinite(value) || value < 0 || value > 100) return null
  return value
}

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid]
}

function historicalTotalEstimateMs(
  job: TranscriptionJob | null | undefined,
  jobs: TranscriptionJob[]
): number | null {
  if (!job?.audio_file?.duration_seconds || job.audio_file.duration_seconds <= 0) return null

  const runtimeFactors = jobs
    .filter((candidate) => {
      if (candidate.id === job.id) return false
      if (candidate.model_id !== job.model_id) return false
      if (candidate.status !== "succeeded") return false
      if (!candidate.started_at || !candidate.finished_at) return false
      return Boolean(candidate.audio_file?.duration_seconds && candidate.audio_file.duration_seconds > 0)
    })
    .map((candidate) => {
      const runtimeMs =
        parseApiDate(candidate.finished_at as string).getTime() -
        parseApiDate(candidate.started_at as string).getTime()
      const audioMs = (candidate.audio_file?.duration_seconds ?? 0) * 1000
      return runtimeMs > 0 && audioMs > 0 ? runtimeMs / audioMs : null
    })
    .filter((value): value is number => value !== null && Number.isFinite(value) && value > 0)

  const medianFactor = median(runtimeFactors)
  if (medianFactor === null) return null
  return job.audio_file.duration_seconds * 1000 * medianFactor
}

export function jobEta(
  job: TranscriptionJob | null | undefined,
  jobs: TranscriptionJob[] = []
): string | null {
  if (!job?.started_at || job.status !== "running") return null

  const elapsedMs = new Date().getTime() - parseApiDate(job.started_at).getTime()
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return null

  const historyTotalMs = historicalTotalEstimateMs(job, jobs)
  const progress = jobProgress(job)

  if (progress === null || progress <= 0) {
    if (historyTotalMs === null) return null
    return formatElapsedMs(Math.max(historyTotalMs - elapsedMs, 0))
  }

  if (progress >= 100) return null

  const liveTotalMs = (elapsedMs * 100) / progress
  const blendedTotalMs =
    historyTotalMs === null
      ? liveTotalMs
      : (() => {
          const liveWeight = Math.min(Math.max((progress - 5) / 35, 0), 1)
          return historyTotalMs * (1 - liveWeight) + liveTotalMs * liveWeight
        })()

  return formatElapsedMs(Math.max(blendedTotalMs - elapsedMs, 0))
}

export function queueWait(job: TranscriptionJob): string {
  if (!job.started_at) {
    if (job.status === "queued") return "Queued"
    if (job.status === "cancelled") return "—"
    return "—"
  }
  return formatElapsedMs(
    parseApiDate(job.started_at).getTime() - parseApiDate(job.created_at).getTime()
  )
}

export function summaryQueueWait(job: TranscriptionJob): string {
  const queuedAt = job.summary_queued_at ?? job.summary_updated_at
  if (!queuedAt) return "—"
  if (!job.summary_started_at) {
    if (job.summary_status === "queued") return "Queued"
    return "—"
  }
  return formatElapsedMs(
    parseApiDate(job.summary_started_at).getTime() - parseApiDate(queuedAt).getTime()
  )
}

export function summaryRuntime(job: TranscriptionJob): string {
  if (!job.summary_started_at) return "Not started"
  const end = job.summary_finished_at ? parseApiDate(job.summary_finished_at) : new Date()
  return formatElapsedMs(end.getTime() - parseApiDate(job.summary_started_at).getTime())
}

export function MetadataItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 text-sm font-medium">{value}</div>
    </div>
  )
}
