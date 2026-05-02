import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, Download, Loader2, Trash2 } from "lucide-react"
import { useSearchParams } from "react-router-dom"
import { toast } from "sonner"

import api from "@/api/client"
import { PaginationControls } from "@/components/PaginationControls"
import { ProjectBadge } from "@/components/ProjectBadge"
import { TranscriptAudioPlayer } from "@/components/TranscriptAudioPlayer"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { audioTitle } from "@/lib/audio"
import { formatDateTimeLocal } from "@/lib/datetime"
import { formatBytes, formatDuration } from "@/lib/format"
import { jobRuntime, MetadataItem } from "@/lib/jobs"
import type { Project, TranscriptionJob } from "@/types"

const PAGE_SIZE = 20

const TRANSCRIPT_OUTPUTS = [
  { format: "txt", label: "Text", sizeKey: "output_txt_size_bytes" },
  { format: "json", label: "JSON", sizeKey: "output_json_size_bytes" },
  { format: "srt", label: "SRT", sizeKey: "output_srt_size_bytes" },
  { format: "vtt", label: "VTT", sizeKey: "output_vtt_size_bytes" },
] as const

export default function Transcriptions() {
  const qc = useQueryClient()
  const [searchParams] = useSearchParams()
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [projectFilter, setProjectFilter] = useState("all")
  const projectParams =
    projectFilter === "all" ? undefined : { project_id: projectFilter }
  const { data: jobs = [], isLoading } = useQuery<TranscriptionJob[]>({
    queryKey: ["transcriptions", projectFilter],
    queryFn: () => api.get("/transcriptions", { params: projectParams }).then((r) => r.data),
    refetchInterval: 5000,
  })
  const { data: projects = [], isLoading: projectsLoading } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.get("/projects").then((r) => r.data),
  })
  useEffect(() => {
    if (projectsLoading || projectFilter === "all" || projectFilter === "none") return
    if (!projects.some((project) => String(project.id) === projectFilter)) {
      setProjectFilter("all")
    }
  }, [projectFilter, projects, projectsLoading])

  const visibleJobs = useMemo(
    () => jobs.filter((job) => job.status === "succeeded" || Boolean(job.partial_transcript_text)),
    [jobs]
  )
  const pageCount = Math.max(1, Math.ceil(visibleJobs.length / PAGE_SIZE))
  const pagedJobs = visibleJobs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const linkedJobId = Number(searchParams.get("job"))

  useEffect(() => {
    if (!linkedJobId) return
    const jobIndex = visibleJobs.findIndex((job) => job.id === linkedJobId)
    if (jobIndex === -1) return
    setExpandedId(linkedJobId)
    setPage(Math.floor(jobIndex / PAGE_SIZE) + 1)
  }, [visibleJobs, linkedJobId])

  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const download = (job: TranscriptionJob, format: string) => {
    window.location.href = `/api/v1/transcriptions/${job.id}/download?format=${format}`
  }

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

  const toggleExpanded = (jobId: number) => {
    setExpandedId((current) => (current === jobId ? null : jobId))
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Transcriptions</h1>
          <p className="text-muted-foreground">Finished transcripts, text viewer, and downloads.</p>
        </div>
        <Select value={projectFilter} onValueChange={setProjectFilter}>
          <SelectTrigger className="w-full sm:w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All projects</SelectItem>
            <SelectItem value="none">Unassigned</SelectItem>
            {projects.map((project) => (
              <SelectItem key={project.id} value={String(project.id)}>
                {project.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : visibleJobs.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No finished or partial transcriptions yet. Check Jobs for queued, running, failed, or cancelled work.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <PaginationControls
            page={page}
            pageCount={pageCount}
            totalItems={visibleJobs.length}
            pageSize={PAGE_SIZE}
            itemLabel="transcriptions"
            onPageChange={setPage}
          />

          {pagedJobs.map((job) => {
            const expanded = expandedId === job.id
            const isFinal = job.status === "succeeded"
            const transcriptText = isFinal ? job.transcript_text : job.partial_transcript_text

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
                      <p className="truncate text-sm font-medium">{audioTitle(job.audio_file, `Job #${job.id}`)}</p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {job.model?.display_name ?? job.model?.variant ?? "model"} · {job.language}
                      </p>
                      {!isFinal && (
                        <Badge variant="outline" className="mt-2 border-amber-300 bg-amber-50 text-amber-800">
                          Partial
                        </Badge>
                      )}
                      <div className="mt-2">
                        <ProjectBadge project={job.audio_file?.project} />
                      </div>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {isFinal
                          ? `Finished ${job.finished_at ? formatDateTimeLocal(job.finished_at) : formatDateTimeLocal(job.created_at)}`
                          : `Partial updated ${job.partial_updated_at ? formatDateTimeLocal(job.partial_updated_at) : formatDateTimeLocal(job.created_at)}`} · Runtime {jobRuntime(job)}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 sm:justify-end">
                    {TRANSCRIPT_OUTPUTS.map((output) => (
                      <span key={output.format} className="rounded-full border bg-muted/30 px-2 py-0.5 text-xs text-muted-foreground">
                        {output.format} {formatBytes(job[output.sizeKey])}
                      </span>
                    ))}
                  </div>
                </button>

                {expanded && (
                  <CardContent className="space-y-4 border-t pt-4">
                    <div className="flex flex-wrap gap-2">
                      {TRANSCRIPT_OUTPUTS.map((output) => (
                        <Button
                          key={output.format}
                          variant="outline"
                          size="sm"
                          disabled={!isFinal}
                          onClick={() => download(job, output.format)}
                        >
                          <Download className="mr-2 h-3 w-3" />
                          {output.format}
                          <span className="ml-2 text-xs text-muted-foreground">{formatBytes(job[output.sizeKey])}</span>
                        </Button>
                      ))}
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <MetadataItem label="Job ID" value={`#${job.id}`} />
                      <MetadataItem label="Runtime" value={jobRuntime(job)} />
                      <MetadataItem
                        label="Audio"
                        value={
                          <div>
                            <p>{formatDuration(job.audio_file?.duration_seconds)} · {formatBytes(job.audio_file?.size_bytes)}</p>
                            {job.audio_file?.notes && (
                              <p className="mt-1 line-clamp-2 text-xs font-normal text-muted-foreground">
                                {job.audio_file.notes}
                              </p>
                            )}
                          </div>
                        }
                      />
                      <MetadataItem label={isFinal ? "Finished" : "Partial Updated"} value={isFinal ? (job.finished_at ? formatDateTimeLocal(job.finished_at) : "Unknown") : (job.partial_updated_at ? formatDateTimeLocal(job.partial_updated_at) : "Unknown")} />
                      <MetadataItem label="Model" value={job.model?.variant ?? "Unknown"} />
                      <MetadataItem label="Language" value={job.language} />
                      <MetadataItem label="Project" value={<ProjectBadge project={job.audio_file?.project} />} />
                      <MetadataItem
                        label="Transcript Files"
                        value={
                          <div className="space-y-1">
                            {TRANSCRIPT_OUTPUTS.map((output) => (
                              <p key={output.format} className="flex justify-between gap-3 text-xs font-normal">
                                <span className="uppercase text-muted-foreground">{output.format}</span>
                                <span>{formatBytes(job[output.sizeKey])}</span>
                              </p>
                            ))}
                          </div>
                        }
                      />
                    </div>

                    <TranscriptAudioPlayer
                      job={job}
                      source={isFinal ? "auto" : "partial"}
                      title={isFinal ? "Live transcript" : "Partial transcript"}
                    />

                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          navigator.clipboard.writeText(transcriptText ?? "")
                          toast.success("Transcript copied")
                        }}
                      >
                        Copy Text
                      </Button>
                      <Button
                        variant="outline"
                        disabled={deleteMutation.isPending || job.status === "running"}
                        className="border-destructive/40 text-destructive hover:bg-destructive/10"
                        onClick={() => {
                          if (window.confirm("Delete this transcription and all generated output files?")) {
                            deleteMutation.mutate(job.id)
                          }
                        }}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete Transcription Files
                      </Button>
                    </div>
                  </CardContent>
                )}
              </Card>
            )
          })}

          <PaginationControls
            page={page}
            pageCount={pageCount}
            totalItems={visibleJobs.length}
            pageSize={PAGE_SIZE}
            itemLabel="transcriptions"
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  )
}
