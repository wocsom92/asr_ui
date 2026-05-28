import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Ban, Brain, ChevronDown, ChevronRight, Copy, FileText, Loader2, Trash2 } from "lucide-react"
import { Link } from "react-router-dom"
import { toast } from "sonner"

import api from "@/api/client"
import { PaginationControls } from "@/components/PaginationControls"
import { TranscriptAudioPlayer } from "@/components/TranscriptAudioPlayer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { audioTitle } from "@/lib/audio"
import { formatDateTimeLocal } from "@/lib/datetime"
import { formatBytes, formatDuration } from "@/lib/format"
import {
  isJobCancelling,
  jobEta,
  jobProgress,
  jobRuntime,
  jobStatusBadgeClass,
  jobStatusLabel,
  MetadataItem,
  queueWait,
  statusIcon,
  summaryQueueWait,
  summaryRuntime,
} from "@/lib/jobs"
import type { TranscriptionJob, TranscriptionJobChunk } from "@/types"

const PAGE_SIZE = 20
const WORKER_COLORS = [
  "bg-blue-600",
  "bg-emerald-600",
  "bg-amber-600",
  "bg-fuchsia-600",
  "bg-cyan-700",
  "bg-rose-600",
  "bg-lime-700",
  "bg-indigo-600",
]

type SummaryJobStatus = Exclude<TranscriptionJob["summary_status"], "idle">

type JobListItem =
  | { kind: "transcription"; id: string; status: TranscriptionJob["status"]; job: TranscriptionJob; sortAt: string }
  | { kind: "summary"; id: string; status: SummaryJobStatus; job: TranscriptionJob; sortAt: string }

function summarySortDate(job: TranscriptionJob) {
  return job.summary_queued_at ?? job.summary_started_at ?? job.summary_updated_at ?? job.created_at
}

function summaryStatusBadgeClass(status: SummaryJobStatus) {
  if (status === "succeeded") return "border-emerald-300 bg-emerald-50 text-emerald-800"
  if (status === "failed") return "border-destructive/40 bg-destructive/10 text-destructive"
  if (status === "cancelled") return "border-gray-300 bg-gray-200 text-gray-800 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200"
  if (status === "running") return "border-blue-300 bg-blue-50 text-blue-800"
  return "border-amber-300 bg-amber-50 text-amber-800"
}

function chunkCoreSeconds(chunk: TranscriptionJobChunk) {
  return Math.max(
    chunk.end_seconds - chunk.start_seconds - chunk.overlap_start_seconds - chunk.overlap_end_seconds,
    0
  )
}

function workerColor(workerName: string | null | undefined, colorMap: Map<string, string>) {
  if (!workerName) return "bg-slate-400"
  return colorMap.get(workerName) ?? "bg-slate-400"
}

function workerColorMap(chunks: TranscriptionJobChunk[]) {
  const workers = Array.from(
    new Set(chunks.map((chunk) => chunk.worker_name_snapshot).filter((name): name is string => Boolean(name)))
  ).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }))
  return new Map(workers.map((worker, index) => [worker, WORKER_COLORS[index % WORKER_COLORS.length]]))
}

function chunkProgress(chunk: TranscriptionJobChunk) {
  if (chunk.status === "succeeded") return 100
  if (chunk.status === "failed" || chunk.status === "cancelled") return 100
  if (chunk.status === "queued") return 0
  const match = (chunk.status_text ?? "").match(/(\d{1,3})%/)
  if (!match) return 35
  const value = Number(match[1])
  return Number.isFinite(value) ? Math.max(5, Math.min(99, value)) : 35
}

function chunkStatusClass(chunk: TranscriptionJobChunk, colorMap: Map<string, string>) {
  if (chunk.status === "failed") return "bg-destructive"
  if (chunk.status === "cancelled") return "bg-gray-500"
  if (chunk.status === "queued") return "bg-slate-300 dark:bg-slate-700"
  return workerColor(chunk.worker_name_snapshot, colorMap)
}

function chunkWorkerLabel(chunk: TranscriptionJobChunk) {
  return chunk.worker_name_snapshot ?? (chunk.status === "queued" ? "Waiting" : "Unassigned")
}

function SplitChunkTimeline({ job }: { job: TranscriptionJob }) {
  const chunks = [...(job.split_chunks ?? [])].sort((a, b) => a.index - b.index)
  if (!job.split_enabled || chunks.length === 0) return null
  const colorMap = workerColorMap(chunks)

  const totalSeconds = Math.max(
    chunks.reduce((sum, chunk) => sum + chunkCoreSeconds(chunk), 0),
    1
  )
  const workers = Array.from(
    new Set(chunks.map((chunk) => chunk.worker_name_snapshot).filter((name): name is string => Boolean(name)))
  ).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }))

  return (
    <div className="space-y-2">
      <div className="flex h-8 overflow-hidden rounded-md border bg-muted">
        {chunks.map((chunk) => {
          const seconds = Math.max(chunkCoreSeconds(chunk), 0.1)
          const basis = `${Math.max(4, (seconds / totalSeconds) * 100)}%`
          const status = chunk.status === "succeeded" ? "done" : chunk.status
          const label = `${chunk.index + 1}. ${chunkWorkerLabel(chunk)}`
          return (
            <div
              key={chunk.id}
              className="relative min-w-8 border-r border-background/70 last:border-r-0"
              style={{ flexBasis: basis, flexGrow: seconds }}
              title={`Chunk ${chunk.index + 1}: ${chunkWorkerLabel(chunk)} · ${status} · ${formatDuration(seconds)}`}
            >
              <div
                className={`absolute inset-y-0 left-0 ${chunkStatusClass(chunk, colorMap)} transition-all`}
                style={{ width: `${chunkProgress(chunk)}%` }}
              />
              <div className="relative flex h-full items-center justify-center px-1 text-[11px] font-medium text-white">
                <span className="truncate drop-shadow-sm">{label}</span>
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        {workers.length === 0 ? (
          <span>Chunks are waiting for workers.</span>
        ) : (
          workers.map((worker) => (
            <span key={worker} className="inline-flex items-center gap-1 rounded-md border bg-muted/30 px-2 py-1">
              <span className={`h-2 w-2 rounded-full ${workerColor(worker, colorMap)}`} />
              {worker}
            </span>
          ))
        )}
        {chunks.some((chunk) => chunk.status === "failed") && (
          <span className="inline-flex items-center gap-1 rounded-md border bg-muted/30 px-2 py-1">
            <span className="h-2 w-2 rounded-full bg-destructive" />
            failed
          </span>
        )}
      </div>
    </div>
  )
}

function SplitProcessedProgress({ job }: { job: TranscriptionJob }) {
  const chunks = [...(job.split_chunks ?? [])].sort((a, b) => a.index - b.index)
  if (!job.split_enabled || chunks.length === 0) return null

  const colorMap = workerColorMap(chunks)
  const totalSeconds = Math.max(
    job.audio_file?.duration_seconds ?? chunks.reduce((sum, chunk) => sum + chunkCoreSeconds(chunk), 0),
    1
  )
  const processedByWorker = new Map<string, number>()
  for (const chunk of chunks) {
    const worker = chunk.worker_name_snapshot ?? "Unassigned"
    const processedSeconds = chunkCoreSeconds(chunk) * (chunkProgress(chunk) / 100)
    processedByWorker.set(worker, (processedByWorker.get(worker) ?? 0) + processedSeconds)
  }
  const segments = Array.from(processedByWorker.entries())
    .map(([worker, seconds]) => ({ worker, seconds, percent: (seconds / totalSeconds) * 100 }))
    .filter((segment) => segment.seconds > 0)
    .sort((a, b) => a.worker.localeCompare(b.worker, undefined, { sensitivity: "base", numeric: true }))
  const processedPercent = Math.min(100, segments.reduce((sum, segment) => sum + segment.percent, 0))

  return (
    <div className="space-y-2">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted">
        {segments.map((segment) => (
          <div
            key={segment.worker}
            className={`${workerColor(segment.worker === "Unassigned" ? null : segment.worker, colorMap)} h-full transition-all`}
            style={{ width: `${Math.max(segment.percent, 0.75)}%` }}
            title={`${segment.worker}: ${formatDuration(segment.seconds)} processed (${Math.round(segment.percent)}% of audio)`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>{Math.round(processedPercent)}% processed</span>
        {segments.map((segment) => (
          <span key={segment.worker} className="inline-flex items-center gap-1">
            <span className={`h-2 w-2 rounded-full ${workerColor(segment.worker === "Unassigned" ? null : segment.worker, colorMap)}`} />
            {segment.worker}: {Math.round(segment.percent)}%
          </span>
        ))}
      </div>
    </div>
  )
}

export default function Jobs() {
  const qc = useQueryClient()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState("all")
  const [page, setPage] = useState(1)
  const { data: jobs = [], isLoading } = useQuery<TranscriptionJob[]>({
    queryKey: ["transcriptions"],
    queryFn: () => api.get("/transcriptions").then((r) => r.data),
    refetchInterval: (query) => {
      const list = query.state.data
      return list?.some(
        (j) =>
          j.status === "queued" ||
          j.status === "running" ||
          isJobCancelling(j) ||
          j.summary_status === "queued" ||
          j.summary_status === "running"
      )
        ? 1500
        : 5000
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (jobId: number) => api.post(`/transcriptions/${jobId}/cancel`).then((r) => r.data),
    onSuccess: (job: TranscriptionJob) => {
      qc.setQueryData<TranscriptionJob[]>(["transcriptions"], (prev) =>
        prev ? prev.map((j) => (j.id === job.id ? job : j)) : prev
      )
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success(
        job.status === "cancelled" ? "Job cancelled" : "Cancellation requested - job will stop shortly"
      )
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not cancel job")
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (jobId: number) => api.delete(`/transcriptions/${jobId}`),
    onSuccess: (_data, jobId) => {
      qc.setQueryData<TranscriptionJob[]>(["transcriptions"], (prev) =>
        prev ? prev.filter((job) => job.id !== jobId) : prev
      )
      if (expandedId === `transcription-${jobId}` || expandedId === `summary-${jobId}`) setExpandedId(null)
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Transcription and output files deleted")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not delete transcription")
    },
  })

  const summaryMutation = useMutation({
    mutationFn: (jobId: number) => api.post<TranscriptionJob>(`/transcriptions/${jobId}/summary`).then((r) => r.data),
    onSuccess: (job: TranscriptionJob) => {
      qc.setQueryData<TranscriptionJob[]>(["transcriptions"], (prev) =>
        prev ? prev.map((j) => (j.id === job.id ? job : j)) : prev
      )
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Summary queued")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not queue summary")
    },
  })

  const cancelSummaryMutation = useMutation({
    mutationFn: (jobId: number) =>
      api.post<TranscriptionJob>(`/transcriptions/${jobId}/summary/cancel`).then((r) => r.data),
    onSuccess: (job: TranscriptionJob) => {
      qc.setQueryData<TranscriptionJob[]>(["transcriptions"], (prev) =>
        prev ? prev.map((j) => (j.id === job.id ? job : j)) : prev
      )
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Summary cancelled")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not cancel summary")
    },
  })

  const listItems = useMemo<JobListItem[]>(() => {
    return jobs.flatMap((job) => {
      const items: JobListItem[] = [
        { kind: "transcription", id: `transcription-${job.id}`, status: job.status, job, sortAt: job.created_at },
      ]
      if (job.summary_status !== "idle") {
        items.push({
          kind: "summary",
          id: `summary-${job.id}`,
          status: job.summary_status,
          job,
          sortAt: summarySortDate(job),
        })
      }
      return items
    }).sort((a, b) => new Date(b.sortAt).getTime() - new Date(a.sortAt).getTime())
  }, [jobs])

  const filteredItems = useMemo(() => {
    if (statusFilter === "all") return listItems
    return listItems.filter((item) => item.status === statusFilter)
  }, [listItems, statusFilter])

  const pageCount = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE))
  const pagedItems = filteredItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => {
    setPage(1)
    setExpandedId(null)
  }, [statusFilter])

  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const toggleExpanded = (itemId: string) => {
    setExpandedId((current) => (current === itemId ? null : itemId))
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Jobs</h1>
          <p className="text-muted-foreground">Queue status, runtime, model, and file details.</p>
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="queued">Queued</SelectItem>
            <SelectItem value="running">Running</SelectItem>
            <SelectItem value="succeeded">Succeeded</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : jobs.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">No jobs yet.</CardContent>
        </Card>
      ) : filteredItems.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">No jobs match this filter.</CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <PaginationControls
            page={page}
            pageCount={pageCount}
            totalItems={filteredItems.length}
            pageSize={PAGE_SIZE}
            itemLabel="jobs"
            onPageChange={setPage}
          />

          {pagedItems.map((item) => {
            if (item.kind === "summary") {
              const job = item.job
              const expanded = expandedId === item.id
              return (
                <Card key={item.id} className={expanded ? "border-primary" : ""}>
                  <button
                    type="button"
                    onClick={() => toggleExpanded(item.id)}
                    className="flex w-full flex-col gap-3 p-4 text-left transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between"
                    aria-expanded={expanded}
                  >
                    <div className="flex min-w-0 flex-1 items-start gap-3">
                      <span className="mt-0.5 text-muted-foreground">
                        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <Brain className="h-4 w-4 text-muted-foreground" />
                          <span className="truncate text-sm font-medium">
                            Summary for {audioTitle(job.audio_file, `Job #${job.id}`)}
                          </span>
                        </div>
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          Parent transcription #{job.id} · {job.summary_model ?? "summary model"} ·{" "}
                          {job.summary_updated_at ? formatDateTimeLocal(job.summary_updated_at) : formatDateTimeLocal(job.created_at)}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                      <Badge variant="outline" className={summaryStatusBadgeClass(item.status)}>
                        Summary {item.status}
                      </Badge>
                      <span className="rounded-md bg-muted/40 px-2 py-1 text-xs">
                        <span className="text-muted-foreground">Type </span>
                        <span className="font-medium">Summarization</span>
                      </span>
                    </div>
                  </button>

                  {expanded && (
                    <CardContent className="space-y-4 border-t pt-4">
                      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <MetadataItem label="Summary Job" value={`#${job.id}`} />
                        <MetadataItem
                          label="Status"
                          value={
                            <Badge variant="outline" className={summaryStatusBadgeClass(item.status)}>
                              Summary {item.status}
                            </Badge>
                          }
                        />
                        <MetadataItem label="Model" value={job.summary_model ?? "Not selected"} />
                        <MetadataItem label="Queued" value={job.summary_queued_at ? formatDateTimeLocal(job.summary_queued_at) : "-"} />
                        <MetadataItem label="Started" value={job.summary_started_at ? formatDateTimeLocal(job.summary_started_at) : "Not started"} />
                        <MetadataItem label="Finished" value={job.summary_finished_at ? formatDateTimeLocal(job.summary_finished_at) : "Not finished"} />
                        <MetadataItem label="Queue wait" value={summaryQueueWait(job)} />
                        <MetadataItem label="Runtime" value={summaryRuntime(job)} />
                        <MetadataItem label="Updated" value={job.summary_updated_at ? formatDateTimeLocal(job.summary_updated_at) : "-"} />
                        <MetadataItem label="Parent Job" value={`#${job.id}`} />
                        <MetadataItem label="Audio" value={audioTitle(job.audio_file, "Unknown file")} />
                      </div>

                      {job.summary_error && (
                        <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
                          {job.summary_error}
                        </p>
                      )}
                      {job.summary_text ? (
                        <div className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-sm leading-relaxed">
                          {job.summary_text}
                        </div>
                      ) : (
                        <p className="rounded-md bg-background p-3 text-sm text-muted-foreground">
                          {job.summary_status === "queued" || job.summary_status === "running"
                            ? "Summary is being generated."
                            : "No summary text is available."}
                        </p>
                      )}

                      <div className="flex flex-wrap gap-2">
                        {job.summary_text && (
                          <Button
                            type="button"
                            variant="outline"
                            className="w-full sm:w-auto"
                            onClick={() => {
                              navigator.clipboard.writeText(job.summary_text ?? "")
                              toast.success("Summary copied")
                            }}
                          >
                            <Copy className="mr-2 h-4 w-4" />
                            Copy summary
                          </Button>
                        )}
                        <Button type="button" variant="outline" className="w-full sm:w-auto" asChild>
                          <Link to={`/transcriptions?job=${job.id}`}>
                            <FileText className="mr-2 h-4 w-4" />
                            Open transcription
                          </Link>
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="w-full sm:w-auto"
                          disabled={summaryMutation.isPending || job.summary_status === "queued" || job.summary_status === "running"}
                          onClick={() => summaryMutation.mutate(job.id)}
                        >
                          {summaryMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Brain className="mr-2 h-4 w-4" />
                          )}
                          {job.summary_text ? "Regenerate summary" : "Generate summary"}
                        </Button>
                        {(job.summary_status === "queued" || job.summary_status === "running") && (
                          <Button
                            type="button"
                            variant="outline"
                            className="w-full sm:w-auto"
                            disabled={cancelSummaryMutation.isPending}
                            onClick={() => cancelSummaryMutation.mutate(job.id)}
                          >
                            {cancelSummaryMutation.isPending ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <Ban className="mr-2 h-4 w-4" />
                            )}
                            Cancel summary
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  )}
                </Card>
              )
            }

            const job = item.job
            const expanded = expandedId === item.id
            const progress = jobProgress(job)
            const eta = jobEta(job, jobs)
            const runningWorkers = job.running_worker_names ?? []
            const runningWorkerLabel = runningWorkers.length > 0 ? runningWorkers.join(", ") : null

            return (
              <Card key={item.id} className={expanded ? "border-primary" : ""}>
                <button
                  type="button"
                  onClick={() => toggleExpanded(item.id)}
                  className="flex w-full flex-col gap-3 p-4 text-left transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between"
                  aria-expanded={expanded}
                >
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <span className="mt-0.5 text-muted-foreground">
                      {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-2">
                        {statusIcon(job)}
                        <span className="truncate text-sm font-medium">{audioTitle(job.audio_file, `Job #${job.id}`)}</span>
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {job.model?.display_name ?? job.model?.variant ?? "model"} · {job.language} ·{" "}
                        {runningWorkerLabel
                          ? `running on ${runningWorkerLabel}`
                          : job.split_enabled
                            ? "split job"
                            : job.worker_name_snapshot
                              ? `worker ${job.worker_name_snapshot}`
                              : `target ${job.preferred_worker_name_snapshot ?? "any worker"}`} ·{" "}
                        {formatDateTimeLocal(job.created_at)}
                      </p>
                      {job.status_text && (
                        <p
                          className={`mt-1 truncate text-xs font-medium ${
                            isJobCancelling(job) ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"
                          }`}
                        >
                          {job.status_text}
                          {eta ? ` · about ${eta} left` : ""}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    <Badge variant="outline" className={jobStatusBadgeClass(job)}>
                      {jobStatusLabel(job)}
                    </Badge>
                    <span className="rounded-md bg-muted/40 px-2 py-1 text-xs">
                      <span className="text-muted-foreground">Runtime </span>
                      <span className="font-medium">{jobRuntime(job)}</span>
                    </span>
                    <span className="rounded-md bg-muted/40 px-2 py-1 text-xs">
                      <span className="text-muted-foreground">Audio </span>
                      <span className="font-medium">{formatDuration(job.audio_file?.duration_seconds)}</span>
                    </span>
                    {runningWorkerLabel && (
                      <span className="rounded-md bg-muted/40 px-2 py-1 text-xs">
                        <span className="text-muted-foreground">Running on </span>
                        <span className="font-medium">{runningWorkerLabel}</span>
                      </span>
                    )}
                  </div>
                </button>

                {job.split_enabled ? (
                  <div className="px-4 pb-4">
                    <SplitProcessedProgress job={job} />
                  </div>
                ) : progress !== null && (
                  <div className="px-4 pb-4">
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
                    </div>
                  </div>
                )}

                {job.split_enabled && (
                  <div className="px-4 pb-4">
                    <SplitChunkTimeline job={job} />
                  </div>
                )}

                {expanded && (
                  <CardContent className="space-y-4 border-t pt-4">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <MetadataItem label="Job ID" value={`#${job.id}`} />
                      <MetadataItem
                        label="Status"
                        value={
                          <Badge variant="outline" className={jobStatusBadgeClass(job)}>
                            {jobStatusLabel(job)}
                          </Badge>
                        }
                      />
                      <MetadataItem label="Runtime" value={jobRuntime(job)} />
                      <MetadataItem label="Progress" value={progress !== null ? `${progress}%` : "-"} />
                      <MetadataItem label="Est. Remaining" value={eta ?? "-"} />
                      <MetadataItem label="Queue Wait" value={queueWait(job)} />
                      <MetadataItem label="Worker" value={job.worker_name_snapshot ?? (job.split_enabled ? "Multiple workers" : "Not assigned")} />
                      <MetadataItem
                        label="Running On"
                        value={runningWorkerLabel ?? (job.status === "running" ? "Assigning worker" : "-")}
                      />
                      <MetadataItem label="Target Worker" value={job.preferred_worker_name_snapshot ?? "Any accepted worker"} />
                      <MetadataItem label="Split" value={job.split_enabled ? `${job.split_chunks_completed}/${job.split_chunk_count} chunks done` : "Off"} />
                      {job.split_enabled && (
                        <MetadataItem
                          label="Chunks"
                          value={`${job.split_chunks_running} running · ${job.split_chunks_queued} queued · ${job.split_chunks_failed} failed${runningWorkerLabel ? ` · ${runningWorkerLabel}` : ""}`}
                        />
                      )}
                      <MetadataItem
                        label="Model"
                        value={
                          <div className="min-w-0">
                            <p className="truncate">{job.model?.display_name ?? "Unknown model"}</p>
                            <p className="truncate text-xs font-normal text-muted-foreground">
                              {job.model?.provider ?? "provider"} · {job.model?.variant ?? "variant"}
                            </p>
                          </div>
                        }
                      />
                      <MetadataItem label="Language" value={job.language} />
                      <MetadataItem
                        label="Audio"
                        value={
                          <div className="min-w-0">
                            <p className="truncate">{audioTitle(job.audio_file, "Unknown file")}</p>
                            <p className="truncate text-xs font-normal text-muted-foreground">
                              {formatDuration(job.audio_file?.duration_seconds)} · {formatBytes(job.audio_file?.size_bytes)}
                            </p>
                            {job.audio_file?.notes && (
                              <p className="mt-1 line-clamp-2 text-xs font-normal text-muted-foreground">
                                {job.audio_file.notes}
                              </p>
                            )}
                          </div>
                        }
                      />
                      <MetadataItem label="Created" value={formatDateTimeLocal(job.created_at)} />
                      <MetadataItem label="Started" value={job.started_at ? formatDateTimeLocal(job.started_at) : "Not started"} />
                      <MetadataItem label="Finished" value={job.finished_at ? formatDateTimeLocal(job.finished_at) : "Not finished"} />
                    </div>

                    {job.error_message && (
                      <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                        {job.error_message}
                      </div>
                    )}

                    {job.status === "succeeded" && (
                      <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                          <div className="min-w-0">
                            <h3 className="flex items-center gap-2 text-sm font-semibold">
                              <Brain className="h-4 w-4" />
                              Summary
                            </h3>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {job.summary_model ? `${job.summary_model} · ` : ""}
                              {job.summary_status || "idle"}
                              {job.summary_started_at ? ` · runtime ${summaryRuntime(job)}` : ""}
                              {job.summary_updated_at ? ` · updated ${formatDateTimeLocal(job.summary_updated_at)}` : ""}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {job.summary_text && (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  navigator.clipboard.writeText(job.summary_text ?? "")
                                  toast.success("Summary copied")
                                }}
                              >
                                <Copy className="mr-2 h-3 w-3" />
                                Copy
                              </Button>
                            )}
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={summaryMutation.isPending || job.summary_status === "queued" || job.summary_status === "running"}
                              onClick={() => summaryMutation.mutate(job.id)}
                            >
                              {summaryMutation.isPending ? (
                                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                              ) : (
                                <Brain className="mr-2 h-3 w-3" />
                              )}
                              {job.summary_text ? "Regenerate" : "Generate"}
                            </Button>
                            {(job.summary_status === "queued" || job.summary_status === "running") && (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={cancelSummaryMutation.isPending}
                                onClick={() => cancelSummaryMutation.mutate(job.id)}
                              >
                                {cancelSummaryMutation.isPending ? (
                                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                                ) : (
                                  <Ban className="mr-2 h-3 w-3" />
                                )}
                                Cancel
                              </Button>
                            )}
                          </div>
                        </div>
                        {job.summary_status !== "idle" && (
                          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <MetadataItem label="Queued" value={job.summary_queued_at ? formatDateTimeLocal(job.summary_queued_at) : "-"} />
                            <MetadataItem label="Started" value={job.summary_started_at ? formatDateTimeLocal(job.summary_started_at) : "Not started"} />
                            <MetadataItem label="Queue wait" value={summaryQueueWait(job)} />
                            <MetadataItem label="Runtime" value={summaryRuntime(job)} />
                          </div>
                        )}
                        {job.summary_error && (
                          <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
                            {job.summary_error}
                          </p>
                        )}
                        {job.summary_text ? (
                          <div className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-sm leading-relaxed">
                            {job.summary_text}
                          </div>
                        ) : (
                          <p className="rounded-md bg-background p-3 text-sm text-muted-foreground">
                            {job.summary_status === "queued" || job.summary_status === "running"
                              ? "Summary is being generated."
                              : "No summary generated yet."}
                          </p>
                        )}
                      </div>
                    )}

                    {job.partial_transcript_text && (
                      <div className="space-y-2">
                        <div>
                          <h3 className="text-sm font-semibold">Partial transcript</h3>
                          <p className="text-xs text-muted-foreground">
                            Updated {job.partial_updated_at ? formatDateTimeLocal(job.partial_updated_at) : "while running"}
                          </p>
                        </div>
                        <TranscriptAudioPlayer job={job} source="partial" title="Partial transcript" />
                      </div>
                    )}

                    <div className="flex flex-wrap gap-2">
                      {job.status === "succeeded" && (
                        <Button type="button" variant="outline" className="w-full sm:w-auto" asChild>
                          <Link to={`/transcriptions?job=${job.id}`}>
                            <FileText className="mr-2 h-4 w-4" />
                            Open transcription
                          </Link>
                        </Button>
                      )}
                      {(job.status === "queued" || job.status === "running") && (
                        <Button
                          type="button"
                          variant="outline"
                          className="w-full sm:w-auto"
                          disabled={cancelMutation.isPending || isJobCancelling(job)}
                          onClick={() => cancelMutation.mutate(job.id)}
                        >
                          {cancelMutation.isPending || isJobCancelling(job) ? "Cancelling..." : "Cancel job"}
                        </Button>
                      )}
                      {job.status !== "running" && (
                        <Button
                          type="button"
                          variant="outline"
                          className="w-full border-destructive/40 text-destructive hover:bg-destructive/10 sm:w-auto"
                          disabled={deleteMutation.isPending}
                          onClick={() => {
                            if (window.confirm("Delete this transcription and all generated output files?")) {
                              deleteMutation.mutate(job.id)
                            }
                          }}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Delete transcription files
                        </Button>
                      )}
                    </div>
                  </CardContent>
                )}
              </Card>
            )
          })}

          <PaginationControls
            page={page}
            pageCount={pageCount}
            totalItems={filteredItems.length}
            pageSize={PAGE_SIZE}
            itemLabel="jobs"
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  )
}
