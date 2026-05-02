import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Cpu, HardDriveDownload, Loader2, Pencil, ServerCog, Trash2 } from "lucide-react"
import { toast } from "sonner"

import api from "@/api/client"
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
import { formatDateTimeLocal } from "@/lib/datetime"
import { formatBytes, formatDuration } from "@/lib/format"
import type { ModelCatalogItem, TranscriptionWorker } from "@/types"

function statusClass(worker: TranscriptionWorker) {
  if (!worker.accepted) return "border-amber-500/25 bg-amber-500 text-white"
  if (!worker.online) return "border-gray-300 bg-gray-200 text-gray-800"
  if (worker.status === "running") return "border-blue-600/25 bg-blue-600 text-white"
  if (worker.status === "installing" || worker.status === "uninstalling") return "border-amber-500/25 bg-amber-500 text-white"
  return "border-green-600/25 bg-green-600 text-white"
}

function speed(worker: TranscriptionWorker) {
  if (worker.total_audio_seconds <= 0 || worker.total_runtime_seconds <= 0) return "-"
  return formatDuration((worker.total_runtime_seconds / worker.total_audio_seconds) * 3600)
}

function modelSpeedLabel(catalog: ModelCatalogItem[], variant: string) {
  const item = catalog.find((model) => (model.model_variant || model.variant) === variant || model.variant === variant)
  return item?.display_name ?? variant
}

export default function Workers() {
  const qc = useQueryClient()
  const [editingWorker, setEditingWorker] = useState<TranscriptionWorker | null>(null)
  const [displayName, setDisplayName] = useState("")
  const { data: workers = [], isLoading } = useQuery<TranscriptionWorker[]>({
    queryKey: ["workers"],
    queryFn: () => api.get("/workers").then((r) => r.data),
    refetchInterval: 3000,
  })
  const { data: catalog = [] } = useQuery<ModelCatalogItem[]>({
    queryKey: ["models", "catalog"],
    queryFn: () => api.get("/models/catalog").then((r) => r.data),
    retry: false,
  })
  const sortedWorkers = [...workers].sort((a, b) =>
    (a.display_name || a.name).localeCompare(b.display_name || b.name, undefined, {
      sensitivity: "base",
      numeric: true,
    })
  )

  const online = sortedWorkers.filter((worker) => worker.online)
  const running = sortedWorkers.filter((worker) => worker.online && worker.status === "running")
  const installing = sortedWorkers.filter((worker) => worker.online && worker.status === "installing")
  const pending = sortedWorkers.filter((worker) => !worker.accepted)
  const updateMutation = useMutation({
    mutationFn: () =>
      api.patch(`/workers/${editingWorker?.id}`, {
        display_name: displayName,
      }),
    onSuccess: () => {
      setEditingWorker(null)
      void qc.invalidateQueries({ queryKey: ["workers"] })
      toast.success("Worker name updated")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not update worker")
    },
  })
  const acceptMutation = useMutation({
    mutationFn: (workerId: number) => api.patch(`/workers/${workerId}`, { accepted: true }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workers"] })
      toast.success("Worker accepted")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not accept worker")
    },
  })
  const removeMutation = useMutation({
    mutationFn: (workerId: number) => api.delete(`/workers/${workerId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workers"] })
      toast.success("Worker removed")
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(typeof detail === "string" ? detail : "Could not remove worker")
    },
  })
  const openEdit = (worker: TranscriptionWorker) => {
    setEditingWorker(worker)
    setDisplayName(worker.display_name || worker.name)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Workers</h1>
        <p className="text-muted-foreground">Remote and local transcription capacity.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Online</CardTitle>
            <ServerCog className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{online.length}</div>
            <p className="text-xs text-muted-foreground">{workers.length} registered</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Running</CardTitle>
            <Loader2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{running.length}</div>
            <p className="text-xs text-muted-foreground">active jobs or chunks</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Installing</CardTitle>
            <HardDriveDownload className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{installing.length}</div>
            <p className="text-xs text-muted-foreground">auto model downloads</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completed</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {sortedWorkers.reduce((sum, worker) => sum + worker.completed_job_count, 0)}
            </div>
            <p className="text-xs text-muted-foreground">{pending.length} pending approval</p>
          </CardContent>
        </Card>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : workers.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No workers have registered yet.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {sortedWorkers.map((worker) => (
            <Card key={worker.id}>
              <CardHeader className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="truncate text-base">{worker.display_name || worker.name}</CardTitle>
                    {worker.display_name && (
                      <p className="truncate text-xs text-muted-foreground">{worker.name}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge variant="outline" className={statusClass(worker)}>
                      {!worker.accepted ? "pending" : worker.online ? worker.status : "offline"}
                    </Badge>
                    {!worker.accepted && (
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => acceptMutation.mutate(worker.id)}
                        disabled={acceptMutation.isPending}
                      >
                        <Check className="h-4 w-4" />
                      </Button>
                    )}
                    <Button variant="outline" size="icon" onClick={() => openEdit(worker)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => removeMutation.mutate(worker.id)}
                      disabled={removeMutation.isPending || (worker.online && worker.status === "running")}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  {worker.accepted ? "Accepted" : "Waiting for admin approval"} · Last seen{" "}
                  {worker.last_heartbeat_at ? formatDateTimeLocal(worker.last_heartbeat_at) : "never"}
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-md border bg-muted/30 p-3">
                    <p className="text-xs text-muted-foreground">Done</p>
                    <p className="text-sm font-semibold">{worker.completed_job_count}</p>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <p className="text-xs text-muted-foreground">Failed</p>
                    <p className="text-sm font-semibold">{worker.failed_job_count}</p>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <p className="text-xs text-muted-foreground">Overall speed</p>
                    <p className="text-sm font-semibold">{speed(worker)} / audio hour</p>
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground">Speed by model</p>
                  {worker.model_speed_stats.length === 0 ? (
                    <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                      No per-model samples yet.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {[...worker.model_speed_stats]
                        .sort((a, b) =>
                          modelSpeedLabel(catalog, a.variant).localeCompare(
                            modelSpeedLabel(catalog, b.variant),
                            undefined,
                            { sensitivity: "base", numeric: true },
                          ),
                        )
                        .map((stat) => (
                          <div
                            key={stat.variant}
                            className="grid gap-2 rounded-md border bg-muted/30 p-3 text-xs sm:grid-cols-[minmax(0,1fr)_auto]"
                          >
                            <div className="min-w-0">
                              <p className="truncate font-medium">{modelSpeedLabel(catalog, stat.variant)}</p>
                              <p className="text-muted-foreground">
                                {formatDuration(stat.total_audio_seconds)} audio · {stat.completed_count} samples
                              </p>
                            </div>
                            <p className="font-semibold">
                              {stat.runtime_per_audio_hour_seconds
                                ? `${formatDuration(stat.runtime_per_audio_hour_seconds)} / audio hour`
                                : "-"}
                            </p>
                          </div>
                        ))}
                    </div>
                  )}
                </div>

                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground">Models</p>
                  <div className="flex flex-wrap gap-2">
                    {worker.models.length === 0 ? (
                      <Badge variant="outline">No local models</Badge>
                    ) : (
                      worker.models.map((model) => {
                        const uninstallRequested = worker.requested_uninstalls.includes(model.variant)
                        return (
                          <span
                            key={model.variant}
                            className="inline-flex items-center rounded-md border bg-secondary px-2 py-1 text-xs text-secondary-foreground"
                          >
                            <span>
                              {model.variant} · {formatBytes(model.total_bytes)}
                              {uninstallRequested ? " · uninstall requested" : ""}
                            </span>
                          </span>
                        )
                      })
                    )}
                  </div>
                </div>

                {(worker.requested_installs.length > 0 || worker.requested_uninstalls.length > 0) && (
                  <div className="space-y-1 rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                    {worker.requested_installs.length > 0 && (
                      <p>Install requested: {worker.requested_installs.join(", ")}</p>
                    )}
                    {worker.requested_uninstalls.length > 0 && (
                      <p>Uninstall requested: {worker.requested_uninstalls.join(", ")}</p>
                    )}
                  </div>
                )}

                {worker.installs.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground">Installing</p>
                    <div className="space-y-2">
                      {worker.installs.map((install) => {
                        const pct =
                          install.total_bytes && install.total_bytes > 0
                            ? Math.min(100, (install.downloaded_bytes / install.total_bytes) * 100)
                            : null
                        return (
                          <div key={install.variant} className="space-y-1">
                            <div className="flex justify-between text-xs">
                              <span>{install.variant}</span>
                              <span>{pct === null ? formatBytes(install.downloaded_bytes) : `${pct.toFixed(1)}%`}</span>
                            </div>
                            <div className="h-2 overflow-hidden rounded-full bg-muted">
                              <div className="h-full bg-amber-500" style={{ width: `${pct ?? 20}%` }} />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {worker.last_error && (
                  <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                    {worker.last_error}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={!!editingWorker} onOpenChange={(open) => !open && setEditingWorker(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename worker</DialogTitle>
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
              <Input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder={editingWorker?.name}
              />
              <p className="text-xs text-muted-foreground">
                Worker identity from config: {editingWorker?.name}
              </p>
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
