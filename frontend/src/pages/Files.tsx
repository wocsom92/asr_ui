import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileAudio, Loader2, Pencil, Play, Trash2, Upload } from "lucide-react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import api from "@/api/client"
import { ProjectBadge } from "@/components/ProjectBadge"
import type { AudioFile, Project, TranscriptionJob, TranscriptionModel, TranscriptionWorker } from "@/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { formatDateTimeLocal } from "@/lib/datetime"
import { formatBytes, formatDuration } from "@/lib/format"

const LANGUAGES = [
  { value: "auto", label: "Auto-detect" },
  { value: "en", label: "English" },
  { value: "de", label: "German" },
  { value: "fr", label: "French" },
  { value: "es", label: "Spanish" },
  { value: "it", label: "Italian" },
  { value: "ru", label: "Russian" },
  { value: "uk", label: "Ukrainian" },
  { value: "cs", label: "Czech" },
  { value: "sk", label: "Slovak" },
]

function AudioPreview({ file }: { file: AudioFile }) {
  return (
    <audio
      className="h-9 w-full min-w-48 max-w-full"
      controls
      preload="none"
      src={`/api/v1/files/${file.id}/audio`}
    />
  )
}

function InputSourceBadge({ source }: { source?: string | null }) {
  const normalized = source || "web"
  if (normalized === "telegram") {
    return <Badge variant="outline">Telegram</Badge>
  }
  return <Badge variant="secondary">Web UI</Badge>
}

export default function Files() {
  const qc = useQueryClient()
  const [selectedFile, setSelectedFile] = useState<AudioFile | null>(null)
  const [editingFile, setEditingFile] = useState<AudioFile | null>(null)
  const [editName, setEditName] = useState("")
  const [editNotes, setEditNotes] = useState("")
  const [editProjectId, setEditProjectId] = useState("none")
  const [projectFilter, setProjectFilter] = useState("all")
  const [modelId, setModelId] = useState("")
  const [language, setLanguage] = useState("auto")
  const [splitEnabled, setSplitEnabled] = useState(false)
  const [preferredWorkerId, setPreferredWorkerId] = useState("auto")
  const [splitWorkerIds, setSplitWorkerIds] = useState<number[]>([])
  const [uploadProgress, setUploadProgress] = useState<{
    filename: string
    loaded: number
    total: number | null
    phase: "uploading" | "processing"
  } | null>(null)

  const projectParams =
    projectFilter === "all" ? undefined : { project_id: projectFilter }
  const { data: files = [], isLoading } = useQuery<AudioFile[]>({
    queryKey: ["files", projectFilter],
    queryFn: () => api.get("/files", { params: projectParams }).then((r) => r.data),
  })
  const { data: jobs = [] } = useQuery<TranscriptionJob[]>({
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
  const { data: allModels = [] } = useQuery<TranscriptionModel[]>({
    queryKey: ["models", "usable"],
    queryFn: () => api.get("/models").then((r) => r.data),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some((model) => model.status === "installing")
        ? 1000
        : 5000,
  })
  const { data: workers = [] } = useQuery<TranscriptionWorker[]>({
    queryKey: ["workers", "accepted"],
    queryFn: () => api.get("/workers").then((r) => r.data),
    retry: false,
    refetchInterval: 5000,
  })
  const installedModels = allModels.filter((m) => m.status === "installed")
  const installingModels = allModels.filter((m) => m.status === "installing")
  const acceptedWorkers = workers.filter((worker) => worker.accepted && !worker.is_deleted)
  const finishedJobsByFile = useMemo(() => {
    const grouped = new Map<number, TranscriptionJob[]>()
    jobs
      .filter((job) => job.status === "succeeded")
      .forEach((job) => {
        const modelKey = job.model?.display_name ?? job.model?.variant ?? `Model #${job.model_id}`
        const existing = grouped.get(job.audio_file_id) ?? []
        if (!existing.some((item) => (item.model?.display_name ?? item.model?.variant ?? `Model #${item.model_id}`) === modelKey)) {
          grouped.set(job.audio_file_id, [...existing, job])
        }
      })
    return grouped
  }, [jobs])

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append("upload", file)
      if (projectFilter !== "all" && projectFilter !== "none") {
        form.append("project_id", projectFilter)
      }
      setUploadProgress({
        filename: file.name,
        loaded: 0,
        total: file.size || null,
        phase: "uploading",
      })
      return api.post("/files", form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (event) => {
          setUploadProgress({
            filename: file.name,
            loaded: event.loaded,
            total: event.total ?? file.size ?? null,
            phase:
              event.total && event.loaded >= event.total
                ? "processing"
                : "uploading",
          })
        },
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["files"] })
      setUploadProgress(null)
      toast.success("Audio uploaded")
    },
    onError: (err: any) => {
      setUploadProgress(null)
      toast.error(err.response?.data?.detail || "Upload failed")
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/files/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["files"] })
      qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Audio deleted")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Delete failed"),
  })

  const updateMutation = useMutation({
    mutationFn: () =>
      api.patch(`/files/${editingFile?.id}`, {
        display_name: editName,
        notes: editNotes,
        project_id: editProjectId === "none" ? null : Number(editProjectId),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["files"] })
      qc.invalidateQueries({ queryKey: ["transcriptions"] })
      setEditingFile(null)
      toast.success("Audio details updated")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Update failed"),
  })

  const startMutation = useMutation({
    mutationFn: () =>
      api.post(`/files/${selectedFile?.id}/transcriptions`, {
        model_id: Number(modelId),
        language,
        split_enabled: splitEnabled,
        preferred_worker_id: splitEnabled || preferredWorkerId === "auto" ? null : Number(preferredWorkerId),
        split_worker_ids: splitEnabled ? splitWorkerIds : [],
      }),
    onSuccess: () => {
      setSelectedFile(null)
      qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Transcription queued")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not start transcription"),
  })

  const selectedModel = useMemo(
    () => installedModels.find((model) => String(model.id) === modelId),
    [installedModels, modelId]
  )
  const languageOptions =
    selectedModel?.language_mode === "english"
      ? LANGUAGES.filter((l) => l.value === "en" || l.value === "auto")
      : selectedModel?.language_mode === "russian"
        ? LANGUAGES.filter((l) => l.value === "ru" || l.value === "auto")
        : LANGUAGES

  const openRunDialog = (file: AudioFile) => {
    setSelectedFile(file)
    setModelId("")
    setLanguage("auto")
    setSplitEnabled(false)
    const raspiWorker = acceptedWorkers.find((worker) => worker.name === "raspi5")
    setPreferredWorkerId(raspiWorker ? String(raspiWorker.id) : "auto")
    const defaultSplitWorkers = [
      ...(raspiWorker ? [raspiWorker.id] : []),
      ...acceptedWorkers
        .filter((worker) => worker.id !== raspiWorker?.id)
        .slice(0, 1)
        .map((worker) => worker.id),
    ]
    setSplitWorkerIds(defaultSplitWorkers)
  }

  const openEditDialog = (file: AudioFile) => {
    setEditingFile(file)
    setEditName(file.display_name || file.original_filename)
    setEditNotes(file.notes || "")
    setEditProjectId(file.project_id ? String(file.project_id) : "none")
  }

  const handleModelChange = (value: string) => {
    setModelId(value)
    const model = installedModels.find((item) => String(item.id) === value)
    setLanguage(
      model?.language_mode === "english"
        ? "en"
        : model?.language_mode === "russian"
          ? "ru"
          : "auto"
    )
  }

  const toggleSplitWorker = (workerId: number) => {
    setSplitWorkerIds((current) =>
      current.includes(workerId)
        ? current.filter((id) => id !== workerId)
        : [...current, workerId]
    )
  }

  const TranscriptionLabels = ({ file }: { file: AudioFile }) => {
    const finishedJobs = finishedJobsByFile.get(file.id) ?? []
    if (finishedJobs.length === 0) return null

    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {finishedJobs.map((job) => (
          <Badge key={job.id} variant="secondary" className="p-0">
            <Link className="px-2.5 py-0.5" to={`/transcriptions?job=${job.id}`}>
              {job.model?.display_name ?? job.model?.variant ?? `Model #${job.model_id}`}
            </Link>
          </Badge>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Audio Files</h1>
          <p className="text-muted-foreground">Upload iPhone recordings and other audio files.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
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
          <Label className="inline-flex cursor-pointer items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
            {uploadMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
            Upload Audio
            <Input
              type="file"
              accept="audio/*,.m4a,.aac,.mp4,.mov,.wav,.mp3,.flac,.ogg,.webm"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) uploadMutation.mutate(file)
                event.currentTarget.value = ""
              }}
            />
          </Label>
        </div>
      </div>

      {uploadProgress && (
        <Card>
          <CardContent className="space-y-3 py-4">
            <div className="flex items-center justify-between gap-3 text-sm">
              <div className="min-w-0">
                <p className="truncate font-medium">{uploadProgress.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {uploadProgress.phase === "processing"
                    ? "Processing audio metadata"
                    : "Uploading audio"}
                </p>
              </div>
              <span className="shrink-0 text-xs font-medium">
                {uploadProgress.total
                  ? `${Math.min(100, (uploadProgress.loaded / uploadProgress.total) * 100).toFixed(1)}%`
                  : formatBytes(uploadProgress.loaded)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full bg-primary transition-all ${
                  uploadProgress.total ? "" : "w-1/3 animate-pulse"
                }`}
                style={
                  uploadProgress.total
                    ? {
                        width: `${Math.max(
                          1,
                          Math.min(
                            100,
                            (uploadProgress.loaded / uploadProgress.total) * 100
                          )
                        )}%`,
                      }
                    : undefined
                }
              />
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{formatBytes(uploadProgress.loaded)} uploaded</span>
              <span>
                {uploadProgress.total
                  ? `${formatBytes(uploadProgress.total)} total`
                  : "Total size unknown"}
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : files.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
            <FileAudio className="h-10 w-10 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No audio files uploaded yet.</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="hidden overflow-hidden rounded-lg border md:block">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="p-3 text-left font-medium">File</th>
                  <th className="p-3 text-left font-medium">Preview</th>
                  <th className="p-3 text-left font-medium">Duration</th>
                  <th className="p-3 text-left font-medium">Size</th>
                  <th className="p-3 text-left font-medium">Uploaded</th>
                  <th className="p-3 text-left font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {files.map((file) => (
                  <tr key={file.id}>
                    <td className="max-w-[360px] p-3">
                      <p className="truncate font-medium">{file.display_name || file.original_filename}</p>
                      <p className="truncate text-xs text-muted-foreground">{file.original_filename}</p>
                      {file.notes && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{file.notes}</p>}
                      <div className="mt-2">
                        <div className="flex flex-wrap gap-2">
                          <InputSourceBadge source={file.source} />
                          <ProjectBadge project={file.project} />
                        </div>
                      </div>
                      <TranscriptionLabels file={file} />
                    </td>
                    <td className="w-[280px] p-3">
                      <AudioPreview file={file} />
                    </td>
                    <td className="p-3 text-muted-foreground">{formatDuration(file.duration_seconds)}</td>
                    <td className="p-3 text-muted-foreground">{formatBytes(file.size_bytes)}</td>
                    <td className="p-3 text-muted-foreground">{formatDateTimeLocal(file.created_at)}</td>
                    <td className="p-3">
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => openRunDialog(file)}>
                          <Play className="mr-2 h-3 w-3" /> Run
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => openEditDialog(file)}>
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => deleteMutation.mutate(file.id)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-3 md:hidden">
            {files.map((file) => (
              <Card key={file.id}>
                <CardHeader className="pb-3">
                  <CardTitle className="truncate text-base">{file.display_name || file.original_filename}</CardTitle>
                  <p className="truncate text-xs text-muted-foreground">{file.original_filename}</p>
                </CardHeader>
                <CardContent className="space-y-3">
                  {file.notes && <p className="text-sm text-muted-foreground">{file.notes}</p>}
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">{formatDuration(file.duration_seconds)}</Badge>
                    <Badge variant="outline">{formatBytes(file.size_bytes)}</Badge>
                    <InputSourceBadge source={file.source} />
                    <ProjectBadge project={file.project} />
                  </div>
                  <TranscriptionLabels file={file} />
                  <AudioPreview file={file} />
                  <p className="text-xs text-muted-foreground">{formatDateTimeLocal(file.created_at)}</p>
                  <div className="flex gap-2">
                    <Button className="flex-1" onClick={() => openRunDialog(file)}>
                      <Play className="mr-2 h-4 w-4" /> Run
                    </Button>
                    <Button variant="outline" size="icon" onClick={() => openEditDialog(file)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="outline" size="icon" onClick={() => deleteMutation.mutate(file.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}

      <Dialog open={!!selectedFile} onOpenChange={(open) => !open && setSelectedFile(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Run transcription</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Audio</Label>
              <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
                <p className="truncate font-medium">{selectedFile?.display_name || selectedFile?.original_filename}</p>
                {selectedFile?.notes && <p className="mt-1 text-xs text-muted-foreground">{selectedFile.notes}</p>}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Model</Label>
              {installedModels.length === 0 ? (
                <div className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
                  {installingModels.length > 0
                    ? `${installingModels.length} model${installingModels.length === 1 ? "" : "s"} installing. You can queue a job after one finishes.`
                    : "No installed models yet. Install a model from the Models page first."}
                </div>
              ) : (
                <Select value={modelId} onValueChange={handleModelChange}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose installed model" />
                  </SelectTrigger>
                  <SelectContent>
                    {installedModels.map((model) => (
                      <SelectItem key={model.id} value={String(model.id)}>
                        {model.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {selectedModel && (
                <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <span>Variant: {selectedModel.variant}</span>
                    <span>Language profile: {selectedModel.language_mode}</span>
                    <span>Size: {formatBytes(selectedModel.size_bytes)}</span>
                  </div>
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label>Language</Label>
              <Select value={language} onValueChange={setLanguage} disabled={!selectedModel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {languageOptions.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between rounded-md border p-3">
              <div>
                <Label htmlFor="split-transcription">Split across workers</Label>
                <p className="text-xs text-muted-foreground">
                  Optional for long recordings. Normal single-worker mode remains the default.
                </p>
              </div>
              <Switch
                id="split-transcription"
                checked={splitEnabled}
                onCheckedChange={setSplitEnabled}
              />
            </div>
            {splitEnabled ? (
              <div className="space-y-2">
                <Label>Splitter workers</Label>
                <div className="grid gap-2 sm:grid-cols-2">
                  {acceptedWorkers.map((worker) => {
                    const checked = splitWorkerIds.includes(worker.id)
                    return (
                      <Button
                        key={worker.id}
                        type="button"
                        variant={checked ? "default" : "outline"}
                        className="justify-start"
                        onClick={() => toggleSplitWorker(worker.id)}
                      >
                        {worker.display_name || worker.name}
                        {worker.name === "raspi5" ? " (default)" : ""}
                      </Button>
                    )
                  })}
                </div>
                <p className="text-xs text-muted-foreground">
                  Chunks will only be claimed by selected splitter workers. Choose at least two.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                <Label>Worker</Label>
                <Select value={preferredWorkerId} onValueChange={setPreferredWorkerId}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Any accepted worker</SelectItem>
                    {acceptedWorkers.map((worker) => (
                      <SelectItem key={worker.id} value={String(worker.id)}>
                        {worker.display_name || worker.name}
                        {worker.name === "raspi5" ? " (default)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  The selected worker will be the only worker allowed to claim this job.
                </p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              onClick={() => startMutation.mutate()}
              disabled={!modelId || startMutation.isPending || (splitEnabled && splitWorkerIds.length < 2)}
            >
              {startMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Queue Job
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editingFile} onOpenChange={(open) => !open && setEditingFile(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit audio details</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              updateMutation.mutate()
            }}
          >
            <div className="space-y-2">
              <Label>Display name</Label>
              <Input value={editName} onChange={(event) => setEditName(event.target.value)} required />
              <p className="text-xs text-muted-foreground">Original file: {editingFile?.original_filename}</p>
            </div>
            <div className="space-y-2">
              <Label>Notes</Label>
              <Textarea
                className="min-h-28"
                value={editNotes}
                onChange={(event) => setEditNotes(event.target.value)}
                placeholder="Add context, speakers, source, or anything useful for this recording."
              />
            </div>
            <div className="space-y-2">
              <Label>Project</Label>
              <Select value={editProjectId} onValueChange={setEditProjectId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Unassigned</SelectItem>
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={String(project.id)}>
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
