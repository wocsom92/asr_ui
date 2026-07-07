import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Brain, Cpu, Download, Gauge, Loader2, Square, Trash2 } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import type { ModelCatalogItem, ModelStats, SummarizationSettingsResponse, TranscriptionModel, TranscriptionWorker } from "@/types"
import { useConfirm } from "@/components/ConfirmDialog"
import { useAuthStore } from "@/stores/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { formatBytes, formatDuration, formatElapsedMs } from "@/lib/format"

function installPercent(model: TranscriptionModel): number | null {
  if (!model.total_bytes || model.total_bytes <= 0) return null
  return Math.max(0, Math.min(100, (model.downloaded_bytes / model.total_bytes) * 100))
}

function InstallProgress({ model }: { model: TranscriptionModel }) {
  const pct = installPercent(model)
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="truncate text-muted-foreground">
          {model.status_text || "Downloading model"}
        </span>
        <span className="shrink-0 font-medium">
          {pct === null ? formatBytes(model.downloaded_bytes) : `${pct.toFixed(1)}%`}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full bg-primary transition-all ${pct === null ? "w-1/3 animate-pulse" : ""}`}
          style={pct === null ? undefined : { width: `${Math.max(pct, 1)}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{formatBytes(model.downloaded_bytes)} downloaded</span>
        <span>{model.total_bytes ? `${formatBytes(model.total_bytes)} total` : "Total size unknown"}</span>
      </div>
    </div>
  )
}

function workerStatsLabel(stats: ModelStats) {
  return stats.worker_name || (stats.worker_id ? `Worker #${stats.worker_id}` : "Unknown worker")
}

function workerLabel(worker: TranscriptionWorker) {
  return worker.display_name || worker.name
}

function installVariantFor(item: ModelCatalogItem) {
  return item.model_variant || item.variant
}

function workerHasModel(worker: TranscriptionWorker, item: ModelCatalogItem) {
  const installVariant = installVariantFor(item)
  return worker.models.some((model) => model.variant === installVariant || model.variant === item.variant)
}

function workerIsInstalling(worker: TranscriptionWorker, item: ModelCatalogItem) {
  const installVariant = installVariantFor(item)
  return worker.installs.some((model) => model.variant === installVariant || model.variant === item.variant)
}

function workerInstallRequested(worker: TranscriptionWorker, item: ModelCatalogItem) {
  const installVariant = installVariantFor(item)
  return worker.requested_installs.some(
    (variant) =>
      variant === item.variant ||
      variant === installVariant ||
      variant.replace(/\.ru$/, "") === installVariant,
  )
}

function installedWorkerVariant(worker: TranscriptionWorker, item: ModelCatalogItem) {
  const installVariant = installVariantFor(item)
  return worker.models.find((model) => model.variant === installVariant || model.variant === item.variant)?.variant
}

export default function Models() {
  const user = useAuthStore((s) => s.user)
  const qc = useQueryClient()
  const confirm = useConfirm()
  const [summaryPullModel, setSummaryPullModel] = useState("qwen2.5:1.5b")
  const { data: catalog = [], isLoading: catalogLoading } = useQuery<ModelCatalogItem[]>({
    queryKey: ["models", "catalog"],
    queryFn: () => api.get("/models/catalog").then((r) => r.data),
    enabled: user?.role === "admin",
  })
  const { data: summarizationSettings, isLoading: summarizationLoading } = useQuery<SummarizationSettingsResponse>({
    queryKey: ["system", "summarization"],
    queryFn: () => api.get("/system/summarization").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: user?.role === "admin" ? 5000 : false,
  })
  const { data: models = [] } = useQuery<TranscriptionModel[]>({
    queryKey: ["models"],
    queryFn: () => api.get("/models").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: (query) =>
      query.state.data?.some((model) => model.status === "installing")
        ? 1000
        : 5000,
  })
  const { data: modelStats = [] } = useQuery<ModelStats[]>({
    queryKey: ["models", "stats"],
    queryFn: () => api.get("/models/stats").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: 10000,
  })
  const { data: workers = [] } = useQuery<TranscriptionWorker[]>({
    queryKey: ["workers"],
    queryFn: () => api.get("/workers").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: 3000,
  })
  const installMutation = useMutation({
    mutationFn: (variant: string) => api.post("/models/install", { variant }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["models"] })
      toast.success("Model installation started")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Install failed"),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/models/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["models"] })
      toast.success("Model deleted")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Delete failed"),
  })
  const cancelMutation = useMutation({
    mutationFn: (id: number) => api.post(`/models/${id}/cancel`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["models"] })
      toast.success("Model download cancelled")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Cancel failed"),
  })
  const workerInstallMutation = useMutation({
    mutationFn: ({ workerId, variant }: { workerId: number; variant: string }) =>
      api.post(`/workers/${workerId}/install-model`, { variant }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workers"] })
      toast.success("Worker model install requested")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not request worker install"),
  })
  const workerUninstallMutation = useMutation({
    mutationFn: ({ workerId, variant }: { workerId: number; variant: string }) =>
      api.post(`/workers/${workerId}/uninstall-model`, { variant }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workers"] })
      toast.success("Worker model uninstall requested")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not request worker uninstall"),
  })
  const pullSummaryModelMutation = useMutation({
    mutationFn: () => api.post("/system/summarization/pull", { model: summaryPullModel.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "summarization"] })
      toast.success("Summary model pull started")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not start summary model pull"),
  })
  const selectSummaryModelMutation = useMutation({
    mutationFn: (selected_model: string) =>
      api.patch("/system/summarization", {
        enabled: summarizationSettings?.enabled ?? false,
        ollama_base_url: summarizationSettings?.ollama_base_url ?? "http://ollama:11434",
        selected_model,
        auto_summarize: summarizationSettings?.auto_summarize ?? false,
        system_prompt: summarizationSettings?.system_prompt ?? "",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "summarization"] })
      toast.success("Summary model selected")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not select summary model"),
  })
  if (user?.role !== "admin") {
    return <div className="py-12 text-center text-muted-foreground">Admin access required.</div>
  }

  const modelByVariant = new Map(models.map((model) => [model.variant, model]))
  const catalogByVariant = new Map(catalog.map((item) => [item.variant, item]))
  const statsByModelId = new Map<number, ModelStats[]>()
  for (const item of modelStats) {
    const current = statsByModelId.get(item.model_id) ?? []
    current.push(item)
    statsByModelId.set(item.model_id, current)
  }
  const installedModels = models
    .filter((model) => model.status === "installed")
    .sort((a, b) => a.display_name.localeCompare(b.display_name))
  const catalogItems = catalog.filter(
    (item) => modelByVariant.get(item.variant)?.status !== "installed"
  )
  const acceptedWorkers = workers
    .filter((worker) => worker.accepted && !worker.is_deleted)
    .sort((a, b) => workerLabel(a).localeCompare(workerLabel(b), undefined, {
      sensitivity: "base",
      numeric: true,
    }))
  const summaryModels = [...(summarizationSettings?.models ?? [])].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true })
  )
  const recommendedSummaryModels = summarizationSettings?.recommended_models ?? []
  const summaryPullStatus = summarizationSettings?.pull_status

  const renderWorkerModelControls = (item: ModelCatalogItem) => {
    if (acceptedWorkers.length === 0) {
      return (
        <p className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
          No accepted workers yet.
        </p>
      )
    }
    return (
      <div className="space-y-2">
        {acceptedWorkers.map((worker) => {
          const installed = workerHasModel(worker, item)
          const installing = workerIsInstalling(worker, item)
          const installRequested = workerInstallRequested(worker, item)
          const installedVariant = installedWorkerVariant(worker, item)
          const uninstallRequested = Boolean(installedVariant && worker.requested_uninstalls.includes(installedVariant))
          const busy = worker.online && ["running", "installing", "uninstalling"].includes(worker.status)
          const disabled =
            workerInstallMutation.isPending ||
            workerUninstallMutation.isPending ||
            installing ||
            installRequested ||
            uninstallRequested ||
            (installed && busy)
          return (
            <div
              key={`${item.variant}-${worker.id}`}
              className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{workerLabel(worker)}</p>
                <p className="text-xs text-muted-foreground">
                  {installed
                    ? `installed${uninstallRequested ? " · uninstall requested" : ""}`
                    : installing
                      ? "installing"
                      : installRequested
                        ? "install requested"
                        : worker.online
                          ? worker.status
                          : "offline"}
                </p>
              </div>
              {installed ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={disabled || !installedVariant}
                  onClick={async () => {
                    if (!installedVariant) return
                    const ok = await confirm({
                      title: "Uninstall model?",
                      description: `${installedVariant} will be removed from ${workerLabel(worker)}.`,
                      confirmLabel: "Uninstall",
                      destructive: true,
                    })
                    if (ok) workerUninstallMutation.mutate({ workerId: worker.id, variant: installedVariant })
                  }}
                >
                  <Trash2 className="mr-2 h-3 w-3" />
                  Uninstall
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={() => workerInstallMutation.mutate({ workerId: worker.id, variant: item.variant })}
                >
                  {workerInstallMutation.isPending && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                  Install
                </Button>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Models</h1>
        <p className="text-muted-foreground">Manage transcription models separately from local summary models.</p>
      </div>

      {catalogLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="space-y-6">
          {installedModels.length > 0 && (
            <section className="space-y-4">
              <div>
                <h2 className="text-xl font-semibold tracking-tight">Installed Transcription Models</h2>
                <p className="text-sm text-muted-foreground">ASR models available for transcription jobs on this device.</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {installedModels.map((model) => {
                  const catalogItem = catalogByVariant.get(model.variant)
                  const stats = (statsByModelId.get(model.id) ?? []).sort((a, b) =>
                    workerStatsLabel(a).localeCompare(workerStatsLabel(b), undefined, {
                      sensitivity: "base",
                      numeric: true,
                    })
                  )
                  return (
                    <Card key={model.id}>
                      <CardHeader>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <CardTitle className="flex items-center gap-2 text-base">
                              <Cpu className="h-4 w-4" />
                              {model.display_name}
                            </CardTitle>
                            <p className="mt-1 text-sm text-muted-foreground">
                              {model.provider} · {model.variant}
                            </p>
                          </div>
                          <Badge variant="default">
                            {model.language_mode}
                          </Badge>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <div className="grid grid-cols-3 gap-3 text-sm">
                          <div>
                            <p className="text-muted-foreground">Size</p>
                            <p className="font-medium">{model.size_bytes ? formatBytes(model.size_bytes) : "Installed"}</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">RAM</p>
                            <p className="font-medium">{catalogItem?.ram_hint ?? "Unknown"}</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">Status</p>
                            <p className="font-medium">{model.status_text ?? "Installed"}</p>
                          </div>
                        </div>
                        <div className="space-y-1 text-xs">
                          <p className="text-muted-foreground">Download URL</p>
                          <a
                            href={model.download_url ?? "#"}
                            target="_blank"
                            rel="noreferrer"
                            className="block break-all rounded-md border bg-muted/40 p-2 text-primary hover:underline"
                          >
                            {model.download_url ?? "Unknown"}
                          </a>
                        </div>
                        <div className="rounded-md border bg-muted/30 p-3">
                          <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                            <Gauge className="h-4 w-4" />
                            Transcription speed
                          </div>
                          {stats.length > 0 ? (
                            <div className="space-y-3">
                              {stats.map((item) => (
                                <div key={`${item.worker_id ?? "unknown"}-${item.worker_name ?? "unknown"}`} className="rounded-md border bg-background/60 p-3">
                                  <div className="mb-2 flex items-center justify-between gap-2">
                                    <p className="truncate text-sm font-medium">{workerStatsLabel(item)}</p>
                                    <Badge variant="outline">{item.completed_job_count} samples</Badge>
                                  </div>
                                  <div className="grid grid-cols-2 gap-3 text-sm">
                                    <div>
                                      <p className="text-muted-foreground">Per audio hour</p>
                                      <p className="font-medium">{formatElapsedMs(item.runtime_per_audio_hour_seconds * 1000)}</p>
                                    </div>
                                    <div>
                                      <p className="text-muted-foreground">Median</p>
                                      <p className="font-medium">
                                        {item.median_runtime_per_audio_hour_seconds
                                          ? formatElapsedMs(item.median_runtime_per_audio_hour_seconds * 1000)
                                          : "Unknown"}
                                      </p>
                                    </div>
                                    <div>
                                      <p className="text-muted-foreground">Audio processed</p>
                                      <p className="font-medium">{formatDuration(item.total_audio_seconds)}</p>
                                    </div>
                                    <div>
                                      <p className="text-muted-foreground">Runtime</p>
                                      <p className="font-medium">{formatElapsedMs(item.total_runtime_seconds * 1000)}</p>
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">
                              No completed jobs with audio duration yet.
                            </p>
                          )}
                        </div>
                        {catalogItem && (
                          <div className="rounded-md border bg-muted/30 p-3">
                            <p className="mb-2 text-sm font-medium">Workers</p>
                            {renderWorkerModelControls(catalogItem)}
                          </div>
                        )}
                        <div className="flex items-center justify-between gap-2">
                          <Badge variant="default">
                            installed
                          </Badge>
                          <Button variant="outline" size="sm" onClick={() => deleteMutation.mutate(model.id)}>
                            <Trash2 className="mr-2 h-3 w-3" /> Delete
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            </section>
          )}

          <section className="space-y-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">Transcription Model Catalog</h2>
              <p className="text-sm text-muted-foreground">Install ASR models or manage unfinished ASR installs.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {catalogItems.map((item) => {
                const installed = modelByVariant.get(item.variant)
                return (
                  <Card key={item.variant}>
                    <CardHeader>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <CardTitle className="flex items-center gap-2 text-base">
                            <Cpu className="h-4 w-4" />
                            {item.display_name}
                          </CardTitle>
                          <p className="mt-1 text-sm text-muted-foreground">{item.provider}</p>
                        </div>
                        <Badge variant={item.language_mode === "english" ? "secondary" : "outline"}>
                          {item.language_mode}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="grid grid-cols-2 gap-3 text-sm">
                        <div>
                          <p className="text-muted-foreground">Disk</p>
                          <p className="font-medium">{item.disk_hint}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">RAM</p>
                          <p className="font-medium">{item.ram_hint}</p>
                        </div>
                      </div>
                      <div className="space-y-1 text-xs">
                        <p className="text-muted-foreground">Download URL</p>
                        <a
                          href={installed?.download_url ?? item.download_url}
                          target="_blank"
                          rel="noreferrer"
                          className="block break-all rounded-md border bg-muted/40 p-2 text-primary hover:underline"
                        >
                          {installed?.download_url ?? item.download_url}
                        </a>
                      </div>
                      {installed?.error_message && (
                        <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">{installed.error_message}</p>
                      )}
                      {installed?.status === "installing" && <InstallProgress model={installed} />}
                      <div className="rounded-md border bg-muted/30 p-3">
                        <p className="mb-2 text-sm font-medium">Workers</p>
                        {renderWorkerModelControls(item)}
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <Badge variant={installed?.status === "failed" ? "destructive" : "secondary"}>
                          {installed ? `${installed.status}${installed.size_bytes ? ` · ${formatBytes(installed.size_bytes)}` : ""}` : "not installed"}
                        </Badge>
                        {installed?.status === "installing" ? (
                          <Button variant="outline" size="sm" onClick={() => cancelMutation.mutate(installed.id)} disabled={cancelMutation.isPending}>
                            <Square className="mr-2 h-3 w-3" /> Cancel
                          </Button>
                        ) : installed?.status === "failed" ? (
                          <Button variant="outline" size="sm" onClick={() => deleteMutation.mutate(installed.id)}>
                            <Trash2 className="mr-2 h-3 w-3" /> Delete
                          </Button>
                        ) : (
                          <Button size="sm" onClick={() => installMutation.mutate(item.variant)}>
                            Install
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">Summary Models</h2>
              <p className="text-sm text-muted-foreground">Ollama models used only for transcript summaries.</p>
            </div>
            {summarizationLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
                <Card>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <CardTitle className="flex items-center gap-2 text-base">
                        <Brain className="h-4 w-4" />
                        Installed Summary Models
                      </CardTitle>
                      <Badge variant={summarizationSettings?.healthy ? "default" : "secondary"}>
                        {summarizationSettings?.healthy ? "Ollama online" : "Ollama offline"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {summarizationSettings?.health_error && (
                      <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">
                        {summarizationSettings.health_error}
                      </p>
                    )}
                    {summaryPullStatus && summaryPullStatus.status !== "idle" && (
                      <div className="rounded-md border bg-muted/30 p-3 text-sm">
                        <p className="font-medium">
                          {summaryPullStatus.model ?? "Summary model"} · {summaryPullStatus.status}
                        </p>
                        {summaryPullStatus.message && (
                          <p className="text-muted-foreground">{summaryPullStatus.message}</p>
                        )}
                        {summaryPullStatus.error && (
                          <p className="text-destructive">{summaryPullStatus.error}</p>
                        )}
                      </div>
                    )}
                    {summaryModels.length === 0 ? (
                      <p className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
                        No Ollama summary models installed.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {summaryModels.map((model) => {
                          const active = model.name === summarizationSettings?.selected_model
                          return (
                            <div
                              key={model.name}
                              className="flex flex-col gap-3 rounded-md border bg-muted/20 p-3 sm:flex-row sm:items-center sm:justify-between"
                            >
                              <div className="min-w-0">
                                <p className="truncate font-medium">{model.name}</p>
                                <p className="text-sm text-muted-foreground">
                                  {model.size ? formatBytes(model.size) : "Size unknown"}
                                  {model.modified_at ? ` · modified ${model.modified_at}` : ""}
                                </p>
                              </div>
                              <div className="flex items-center gap-2">
                                {active && <Badge>active</Badge>}
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={active || selectSummaryModelMutation.isPending}
                                  onClick={() => selectSummaryModelMutation.mutate(model.name)}
                                >
                                  Use for summaries
                                </Button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Download className="h-4 w-4" />
                      Pull Summary Model
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      {recommendedSummaryModels.map((model) => (
                        <Button
                          key={model}
                          type="button"
                          variant={summaryPullModel === model ? "default" : "outline"}
                          size="sm"
                          onClick={() => setSummaryPullModel(model)}
                        >
                          {model}
                        </Button>
                      ))}
                    </div>
                    <Input
                      value={summaryPullModel}
                      onChange={(event) => setSummaryPullModel(event.currentTarget.value)}
                      placeholder="model:tag"
                    />
                    <Button
                      type="button"
                      disabled={
                        pullSummaryModelMutation.isPending ||
                        !summaryPullModel.trim() ||
                        summaryPullStatus?.status === "running"
                      }
                      onClick={() => pullSummaryModelMutation.mutate()}
                    >
                      {pullSummaryModelMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="mr-2 h-4 w-4" />
                      )}
                      Pull Model
                    </Button>
                    <p className="text-sm text-muted-foreground">
                      Summary models are managed by Ollama and do not appear in transcription job model lists.
                    </p>
                  </CardContent>
                </Card>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
