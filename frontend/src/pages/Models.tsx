import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Cpu, Loader2, Square, Trash2 } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import type { ModelCatalogItem, TranscriptionModel } from "@/types"
import { useAuthStore } from "@/stores/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatBytes } from "@/lib/format"

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

export default function Models() {
  const user = useAuthStore((s) => s.user)
  const qc = useQueryClient()
  const { data: catalog = [], isLoading: catalogLoading } = useQuery<ModelCatalogItem[]>({
    queryKey: ["models", "catalog"],
    queryFn: () => api.get("/models/catalog").then((r) => r.data),
    enabled: user?.role === "admin",
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

  if (user?.role !== "admin") {
    return <div className="py-12 text-center text-muted-foreground">Admin access required.</div>
  }

  const modelByVariant = new Map(models.map((model) => [model.variant, model]))
  const catalogByVariant = new Map(catalog.map((item) => [item.variant, item]))
  const installedModels = models
    .filter((model) => model.status === "installed")
    .sort((a, b) => a.display_name.localeCompare(b.display_name))
  const catalogItems = catalog.filter(
    (item) => modelByVariant.get(item.variant)?.status !== "installed"
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Models</h1>
        <p className="text-muted-foreground">Install and manage local whisper.cpp GGML models.</p>
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
                <h2 className="text-xl font-semibold tracking-tight">Installed Models</h2>
                <p className="text-sm text-muted-foreground">Currently available on this device.</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {installedModels.map((model) => {
                  const catalogItem = catalogByVariant.get(model.variant)
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
              <h2 className="text-xl font-semibold tracking-tight">Model Catalog</h2>
              <p className="text-sm text-muted-foreground">Install new models or manage unfinished installs.</p>
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
        </div>
      )}
    </div>
  )
}
