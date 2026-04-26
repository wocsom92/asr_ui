import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, FileText, Loader2, Trash2 } from "lucide-react"
import { Link } from "react-router-dom"
import { toast } from "sonner"

import api from "@/api/client"
import { PaginationControls } from "@/components/PaginationControls"
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
} from "@/lib/jobs"
import type { TranscriptionJob } from "@/types"

const PAGE_SIZE = 20

export default function Jobs() {
  const qc = useQueryClient()
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState("all")
  const [page, setPage] = useState(1)
  const { data: jobs = [], isLoading } = useQuery<TranscriptionJob[]>({
    queryKey: ["transcriptions"],
    queryFn: () => api.get("/transcriptions").then((r) => r.data),
    refetchInterval: (query) => {
      const list = query.state.data
      return list?.some((j) => j.status === "queued" || j.status === "running" || isJobCancelling(j))
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
      if (expandedId === jobId) setExpandedId(null)
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Transcription and output files deleted")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not delete transcription")
    },
  })

  const filteredJobs = useMemo(() => {
    if (statusFilter === "all") return jobs
    if (statusFilter === "running") return jobs.filter((job) => job.status === "running")
    return jobs.filter((job) => job.status === statusFilter)
  }, [jobs, statusFilter])

  const pageCount = Math.max(1, Math.ceil(filteredJobs.length / PAGE_SIZE))
  const pagedJobs = filteredJobs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => {
    setPage(1)
    setExpandedId(null)
  }, [statusFilter])

  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const toggleExpanded = (jobId: number) => {
    setExpandedId((current) => (current === jobId ? null : jobId))
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
      ) : filteredJobs.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">No jobs match this filter.</CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <PaginationControls
            page={page}
            pageCount={pageCount}
            totalItems={filteredJobs.length}
            pageSize={PAGE_SIZE}
            itemLabel="jobs"
            onPageChange={setPage}
          />

          {pagedJobs.map((job) => {
            const expanded = expandedId === job.id
            const progress = jobProgress(job)
            const eta = jobEta(job, jobs)

            return (
              <Card key={job.id} className={expanded ? "border-primary" : ""}>
                <button
                  type="button"
                  onClick={() => toggleExpanded(job.id)}
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
                        {job.model?.display_name ?? job.model?.variant ?? "model"} · {job.language} · {formatDateTimeLocal(job.created_at)}
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
                  </div>
                </button>

                {progress !== null && (
                  <div className="px-4 pb-4">
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
                    </div>
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
            totalItems={filteredJobs.length}
            pageSize={PAGE_SIZE}
            itemLabel="jobs"
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  )
}
