import { useQuery } from "@tanstack/react-query"
import { AudioLines, Brain, CheckCircle2, Cpu, FileAudio, Loader2, ServerCog } from "lucide-react"
import { Link } from "react-router-dom"
import api from "@/api/client"
import type {
  AudioFile,
  SummarizationSettingsResponse,
  TranscriptionJob,
  TranscriptionModel,
  TranscriptionStats,
  TranscriptionWorker,
} from "@/types"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatDateTimeLocal } from "@/lib/datetime"
import { formatBytes, formatDuration } from "@/lib/format"
import { useAuthStore } from "@/stores/auth"
import { audioTitle } from "@/lib/audio"
import { jobStatusBadgeClass, jobStatusLabel } from "@/lib/jobs"

function modelProviderLabel(provider: string) {
  if (provider === "whisper.cpp") return "Whisper"
  if (provider === "gigaam") return "GigaAM"
  return provider
}

function compactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`
  return String(value)
}

export default function Dashboard() {
  const user = useAuthStore((s) => s.user)
  const { data: files = [], isLoading: filesLoading } = useQuery<AudioFile[]>({
    queryKey: ["files"],
    queryFn: () => api.get("/files").then((r) => r.data),
  })
  const { data: jobs = [] } = useQuery<TranscriptionJob[]>({
    queryKey: ["transcriptions"],
    queryFn: () => api.get("/transcriptions").then((r) => r.data),
    refetchInterval: 30000,
  })
  const { data: stats } = useQuery<TranscriptionStats>({
    queryKey: ["transcriptions", "stats"],
    queryFn: () => api.get("/transcriptions/stats").then((r) => r.data),
    refetchInterval: 30000,
  })
  const { data: models = [] } = useQuery<TranscriptionModel[]>({
    queryKey: ["models"],
    queryFn: () => api.get("/models").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: 10000,
  })
  const { data: summarizationSettings } = useQuery<SummarizationSettingsResponse>({
    queryKey: ["system", "summarization"],
    queryFn: () => api.get("/system/summarization").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: 10000,
  })
  const { data: workers = [] } = useQuery<TranscriptionWorker[]>({
    queryKey: ["workers"],
    queryFn: () => api.get("/workers").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: 5000,
  })

  const storage = files.reduce((sum, file) => sum + file.size_bytes, 0)
  const audioDuration = files.reduce((sum, file) => sum + (file.duration_seconds ?? 0), 0)
  const finishedCount = stats?.finished ?? 0
  const transcriptStorage = stats?.transcript_storage_bytes ?? 0
  const completedSummariesCount = stats?.completed_summaries ?? 0
  const activeSummaryCount = stats?.active_summaries ?? 0
  const failedSummaryCount = stats?.failed_summaries ?? 0
  const activeTranscriptionCount = stats?.active_transcriptions ?? 0
  const activeQueueCount = activeTranscriptionCount + activeSummaryCount
  const summaryCoverage = finishedCount > 0
    ? Math.round((completedSummariesCount / finishedCount) * 100)
    : 0
  const summaryWordCount = stats?.summary_word_count ?? 0
  const averageSummaryWords = stats?.average_summary_words ?? 0
  const recent = jobs.slice(0, 8)
  const installedModels = models.filter((model) => model.status === "installed")
  const installedSummaryModels = summarizationSettings?.models ?? []
  const installedModelProviderSummary = Object.entries(
    installedModels.reduce<Record<string, number>>((counts, model) => {
      const label = modelProviderLabel(model.provider)
      counts[label] = (counts[label] ?? 0) + 1
      return counts
    }, {})
  )
    .sort(([a], [b]) => a.localeCompare(b, undefined, { sensitivity: "base" }))
    .map(([provider, count]) => `${count} ${provider}`)
    .join(" · ")
  const onlineWorkerList = workers.filter((worker) => worker.online)
  const availableWorkers = onlineWorkerList.filter(
    (worker) => worker.accepted && worker.current_job_count === 0 && worker.status === "idle"
  )
  const workerNames = availableWorkers
    .map((worker) => worker.display_name || worker.name)
    .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Audio uploads and local Whisper transcription jobs.</p>
      </div>

      {filesLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Audio Files</CardTitle>
              <FileAudio className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{files.length}</div>
              <p className="text-xs text-muted-foreground">
                {formatDuration(audioDuration)} total · {formatBytes(storage)}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Transcriptions</CardTitle>
              <AudioLines className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{finishedCount}</div>
              <p className="text-xs text-muted-foreground">
                {formatBytes(transcriptStorage)} generated
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active Jobs</CardTitle>
              <Loader2 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{activeQueueCount}</div>
              <p className="text-xs text-muted-foreground">
                {activeTranscriptionCount} transcriptions · {activeSummaryCount} summaries
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Summaries</CardTitle>
              <Brain className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{completedSummariesCount}</div>
              <p className="text-xs text-muted-foreground">
                {summaryCoverage}% of finished transcriptions
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Summary Output</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{compactNumber(summaryWordCount)}</div>
              <p className="text-xs text-muted-foreground">
                {failedSummaryCount} failed · {averageSummaryWords > 0 ? `${compactNumber(averageSummaryWords)} avg words` : "no generated summaries"}
              </p>
            </CardContent>
          </Card>
          {user?.role === "admin" && (
            <>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Available Workers</CardTitle>
                  <ServerCog className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{availableWorkers.length}</div>
                  <p className="text-xs text-muted-foreground">
                    {onlineWorkerList.length} online · {workers.length} registered
                  </p>
                  <p className="mt-2 truncate text-xs font-medium">
                    {workerNames.length > 0 ? workerNames.join(", ") : "No idle workers"}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">Models</CardTitle>
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {installedModels.length + installedSummaryModels.length}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {installedModels.length} transcription · {installedSummaryModels.length} summary
                  </p>
                  <p className="mt-2 truncate text-xs font-medium">
                    {installedModelProviderSummary || summarizationSettings?.selected_model
                      ? [
                          installedModelProviderSummary,
                          summarizationSettings?.selected_model
                            ? `summary: ${summarizationSettings.selected_model}`
                            : "",
                        ].filter(Boolean).join(" · ")
                      : "No installed models"}
                  </p>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recent Transcriptions</CardTitle>
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">No transcription jobs yet.</p>
          ) : (
            <div className="space-y-3">
              {recent.map((job) => (
                <div key={job.id} className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={jobStatusBadgeClass(job)}
                      >
                        {jobStatusLabel(job)}
                      </Badge>
                      <p className="truncate text-sm font-medium">{audioTitle(job.audio_file, `Job #${job.id}`)}</p>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {job.model?.variant ?? "model"} · {job.language} · {formatDateTimeLocal(job.created_at)}
                    </p>
                  </div>
                  {job.status === "succeeded" && (
                    <Link
                      className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                      to={`/transcriptions?job=${job.id}`}
                    >
                      Open transcription
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
