import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bot, Brain, Download, Loader2, Plus, RotateCcw, Save, Terminal, Trash2 } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import type {
  CleanupSettingsResponse,
  SummarizationSettingsResponse,
  TelegramAllowedUser,
  TelegramBotSettingsResponse,
  TelegramBotTestResponse,
  TranscriptionModel,
  TranscriptionWorker,
  User,
  WhisperCliSettings,
  WhisperCliSettingsResponse,
} from "@/types"
import { useAuthStore } from "@/stores/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { formatDateLocal } from "@/lib/datetime"

const EMPTY_WHISPER_SETTINGS: WhisperCliSettings = {
  whisper_threads: 4,
  whisper_max_context: 0,
  whisper_use_gpu: false,
  whisper_flash_attn: false,
  whisper_suppress_non_speech: true,
  whisper_suppress_regex: null,
  transcript_filter_regex: null,
}

type TelegramBotForm = {
  enabled: boolean
  bot_token: string
  proxy_url: string
  default_model_id: string
  default_language: string
  split_enabled: boolean
  split_worker_ids: number[]
  allowed_users: TelegramAllowedUser[]
}

const EMPTY_TELEGRAM_FORM: TelegramBotForm = {
  enabled: false,
  bot_token: "",
  proxy_url: "",
  default_model_id: "",
  default_language: "auto",
  split_enabled: false,
  split_worker_ids: [],
  allowed_users: [],
}

type SummarizationForm = {
  enabled: boolean
  ollama_base_url: string
  selected_model: string
  auto_summarize: boolean
  system_prompt: string
}

const EMPTY_SUMMARIZATION_FORM: SummarizationForm = {
  enabled: false,
  ollama_base_url: "http://ollama:11434",
  selected_model: "",
  auto_summarize: false,
  system_prompt:
    "You summarize transcripts into concise meeting notes. Include: 1) a short overview, 2) key points, 3) decisions, and 4) action items. Use the transcript language unless the transcript is mixed. Preserve important names, dates, and concrete commitments.",
}

function buildWhisperCliPreview(config: WhisperCliSettings, executable = "whisper-cli"): string {
  const args = [
    executable,
    "-m",
    "<model>",
    "-f",
    "<input.wav>",
    "-t",
    String(config.whisper_threads),
    "-mc",
    String(config.whisper_max_context),
    "-otxt",
    "-osrt",
    "-ovtt",
    "-oj",
    "-of",
    "<output/transcript>",
  ]
  if (!config.whisper_use_gpu) args.push("-ng")
  if (!config.whisper_flash_attn) args.push("-nfa")
  if (config.whisper_suppress_non_speech) args.push("-sns")
  if (config.whisper_suppress_regex) {
    args.push("--suppress-regex", config.whisper_suppress_regex)
  }
  args.push("-l", "<job language>", "-pp")
  return args.join(" ")
}

export default function Settings() {
  const user = useAuthStore((s) => s.user)
  const qc = useQueryClient()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [whisperForm, setWhisperForm] = useState<WhisperCliSettings>(EMPTY_WHISPER_SETTINGS)
  const [telegramForm, setTelegramForm] = useState<TelegramBotForm>(EMPTY_TELEGRAM_FORM)
  const [summarizationForm, setSummarizationForm] = useState<SummarizationForm>(EMPTY_SUMMARIZATION_FORM)
  const [pullModel, setPullModel] = useState("qwen2.5:1.5b")
  const [customPullModel, setCustomPullModel] = useState("")
  const [cleanupRetentionDays, setCleanupRetentionDays] = useState(7)

  const { data: whisperSettings, isLoading: whisperSettingsLoading } = useQuery<WhisperCliSettingsResponse>({
    queryKey: ["system", "whisper-cli"],
    queryFn: () => api.get("/system/whisper-cli").then((r) => r.data),
    enabled: user?.role === "admin",
  })
  const { data: telegramSettings, isLoading: telegramSettingsLoading } = useQuery<TelegramBotSettingsResponse>({
    queryKey: ["system", "telegram-bot"],
    queryFn: () => api.get("/system/telegram-bot").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: user?.role === "admin" ? 10000 : false,
  })
  const { data: summarizationSettings, isLoading: summarizationSettingsLoading } = useQuery<SummarizationSettingsResponse>({
    queryKey: ["system", "summarization"],
    queryFn: () => api.get("/system/summarization").then((r) => r.data),
    enabled: user?.role === "admin",
    refetchInterval: user?.role === "admin" ? 5000 : false,
  })
  const { data: users = [] } = useQuery<User[]>({
    queryKey: ["users"],
    queryFn: () => api.get("/users/").then((r) => r.data),
    enabled: user?.role === "admin",
  })
  const { data: models = [] } = useQuery<TranscriptionModel[]>({
    queryKey: ["models"],
    queryFn: () => api.get("/models").then((r) => r.data),
    enabled: user?.role === "admin",
  })
  const { data: workers = [] } = useQuery<TranscriptionWorker[]>({
    queryKey: ["workers"],
    queryFn: () => api.get("/workers").then((r) => r.data),
    enabled: user?.role === "admin",
  })
  const { data: cleanupSettings, isLoading: cleanupSettingsLoading } = useQuery<CleanupSettingsResponse>({
    queryKey: ["system", "cleanup"],
    queryFn: () => api.get("/system/cleanup").then((r) => r.data),
    enabled: user?.role === "admin",
  })

  useEffect(() => {
    if (!whisperSettings) return
    setWhisperForm({
      whisper_threads: whisperSettings.whisper_threads,
      whisper_max_context: whisperSettings.whisper_max_context,
      whisper_use_gpu: whisperSettings.whisper_use_gpu,
      whisper_flash_attn: whisperSettings.whisper_flash_attn,
      whisper_suppress_non_speech: whisperSettings.whisper_suppress_non_speech,
      whisper_suppress_regex: whisperSettings.whisper_suppress_regex,
      transcript_filter_regex: whisperSettings.transcript_filter_regex,
    })
  }, [whisperSettings])

  useEffect(() => {
    if (!telegramSettings) return
    setTelegramForm({
      enabled: telegramSettings.enabled,
      bot_token: "",
      proxy_url: telegramSettings.proxy_url ?? "",
      default_model_id: telegramSettings.default_model_id ? String(telegramSettings.default_model_id) : "",
      default_language: telegramSettings.default_language || "auto",
      split_enabled: telegramSettings.split_enabled,
      split_worker_ids: telegramSettings.split_worker_ids,
      allowed_users: telegramSettings.allowed_users,
    })
  }, [telegramSettings])

  useEffect(() => {
    if (!summarizationSettings) return
    setSummarizationForm({
      enabled: summarizationSettings.enabled,
      ollama_base_url: summarizationSettings.ollama_base_url,
      selected_model: summarizationSettings.selected_model,
      auto_summarize: summarizationSettings.auto_summarize,
      system_prompt: summarizationSettings.system_prompt,
    })
  }, [summarizationSettings])

  useEffect(() => {
    if (!cleanupSettings) return
    setCleanupRetentionDays(cleanupSettings.failed_cancelled_retention_days)
  }, [cleanupSettings])

  const passwordMutation = useMutation({
    mutationFn: () =>
      api.put("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      }),
    onSuccess: () => {
      setCurrentPassword("")
      setNewPassword("")
      toast.success("Password changed")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Password change failed"),
  })
  const updateWhisperMutation = useMutation({
    mutationFn: () =>
      api.patch("/system/whisper-cli", {
        ...whisperForm,
        whisper_suppress_regex: whisperForm.whisper_suppress_regex || null,
        transcript_filter_regex: whisperForm.transcript_filter_regex || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "whisper-cli"] })
      toast.success("Whisper CLI settings saved")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not save Whisper CLI settings"),
  })
  const resetWhisperMutation = useMutation({
    mutationFn: () => api.post("/system/whisper-cli/reset"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "whisper-cli"] })
      toast.success("Whisper CLI settings reset")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not reset Whisper CLI settings"),
  })
  const updateTelegramMutation = useMutation({
    mutationFn: () => {
      const payload: any = {
        enabled: telegramForm.enabled,
        proxy_url: telegramForm.proxy_url || null,
        default_model_id: telegramForm.default_model_id ? Number(telegramForm.default_model_id) : null,
        default_language: telegramForm.default_language,
        split_enabled: telegramForm.split_enabled,
        split_worker_ids: telegramForm.split_worker_ids,
        allowed_users: telegramForm.allowed_users,
      }
      if (telegramForm.bot_token.trim()) {
        payload.bot_token = telegramForm.bot_token.trim()
      }
      return api.patch("/system/telegram-bot", payload)
    },
    onSuccess: () => {
      setTelegramForm((current) => ({ ...current, bot_token: "" }))
      qc.invalidateQueries({ queryKey: ["system", "telegram-bot"] })
      toast.success("Telegram bot settings saved")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not save Telegram bot settings"),
  })
  const updateSummarizationMutation = useMutation({
    mutationFn: () => api.patch("/system/summarization", summarizationForm),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "summarization"] })
      toast.success("Summarization settings saved")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not save summarization settings"),
  })
  const selectedPullModel = pullModel === "custom" ? customPullModel.trim() : pullModel.trim()
  const pullSummarizationModelMutation = useMutation({
    mutationFn: () => api.post("/system/summarization/pull", { model: selectedPullModel }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "summarization"] })
      toast.success("Ollama model pull started")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not start model pull"),
  })
  const testTelegramMutation = useMutation({
    mutationFn: () => api.post<TelegramBotTestResponse>("/system/telegram-bot/test"),
    onSuccess: (response) => {
      if (response.data.ok) {
        toast.success(`Telegram bot connected${response.data.username ? `: @${response.data.username}` : ""}`)
      } else {
        toast.error(response.data.error || "Telegram bot test failed")
      }
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Telegram bot test failed"),
  })
  const restartTelegramMutation = useMutation({
    mutationFn: () => api.post("/system/telegram-bot/restart"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "telegram-bot"] })
      toast.success("Telegram bot restarted")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not restart Telegram bot"),
  })
  const updateCleanupMutation = useMutation({
    mutationFn: () =>
      api.patch("/system/cleanup", {
        failed_cancelled_retention_days: cleanupRetentionDays,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system", "cleanup"] })
      toast.success("Cleanup settings saved")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not save cleanup settings"),
  })

  const updateWhisperField = <K extends keyof WhisperCliSettings>(
    key: K,
    value: WhisperCliSettings[K]
  ) => {
    setWhisperForm((current) => ({ ...current, [key]: value }))
  }
  const updateSummarizationField = <K extends keyof SummarizationForm>(
    key: K,
    value: SummarizationForm[K]
  ) => {
    setSummarizationForm((current) => ({ ...current, [key]: value }))
  }
  const whisperCliPreview = buildWhisperCliPreview(
    whisperForm,
    whisperSettings?.cli_preview?.[0] ?? "whisper-cli"
  )
  const installedModels = models.filter((model) => model.status === "installed")
  const selectedTelegramModel = installedModels.find((model) => String(model.id) === telegramForm.default_model_id)
  const updateTelegramMapping = (
    index: number,
    key: keyof TelegramAllowedUser,
    value: number
  ) => {
    setTelegramForm((current) => ({
      ...current,
      allowed_users: current.allowed_users.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [key]: value } : item
      ),
    }))
  }
  const addTelegramMapping = () => {
    setTelegramForm((current) => ({
      ...current,
      allowed_users: [
        ...current.allowed_users,
        {
          telegram_user_id: 0,
          app_user_id: users[0]?.id ?? 0,
          preferred_worker_id: null,
          preferred_model_id: null,
          split_enabled: null,
          split_worker_ids: [],
        },
      ],
    }))
  }
  const removeTelegramMapping = (index: number) => {
    setTelegramForm((current) => ({
      ...current,
      allowed_users: current.allowed_users.filter((_, itemIndex) => itemIndex !== index),
    }))
  }
  const toggleTelegramSplitWorker = (workerId: number) => {
    setTelegramForm((current) => {
      const hasWorker = current.split_worker_ids.includes(workerId)
      return {
        ...current,
        split_worker_ids: hasWorker
          ? current.split_worker_ids.filter((id) => id !== workerId)
          : [...current.split_worker_ids, workerId],
      }
    })
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Account details, password, and transcription settings.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p><span className="text-muted-foreground">Username:</span> {user?.username}</p>
          <p><span className="text-muted-foreground">Email:</span> {user?.email}</p>
          <Badge>{user?.role}</Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change Password</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              passwordMutation.mutate()
            }}
          >
            <div className="space-y-2">
              <Label>Current password</Label>
              <Input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label>New password</Label>
              <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
            </div>
            <Button type="submit" disabled={passwordMutation.isPending}>
              {passwordMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Update Password
            </Button>
          </form>
        </CardContent>
      </Card>

      {user?.role === "admin" && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Automatic Cleanup</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {cleanupSettingsLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
                    <div className="space-y-2">
                      <Label>Failed/cancelled job retention</Label>
                      <Input
                        type="number"
                        min={1}
                        max={3650}
                        value={cleanupRetentionDays}
                        onChange={(event) => setCleanupRetentionDays(Number(event.currentTarget.value))}
                      />
                      <p className="text-xs text-muted-foreground">
                        Failed and cancelled transcription jobs older than this many days are deleted automatically.
                      </p>
                    </div>
                    <Button
                      type="button"
                      disabled={updateCleanupMutation.isPending}
                      onClick={() => updateCleanupMutation.mutate()}
                    >
                      {updateCleanupMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Save className="mr-2 h-4 w-4" />
                      )}
                      Save Cleanup
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Last cleanup run deleted {cleanupSettings?.deleted_count_last_run ?? 0} jobs.
                  </p>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Brain className="h-4 w-4" />
                Summarization
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {summarizationSettingsLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="grid gap-3 rounded-md border bg-muted/20 p-3 text-sm md:grid-cols-2">
                    <div>
                      <span className="text-muted-foreground">Ollama:</span>{" "}
                      <Badge variant={summarizationSettings?.healthy ? "default" : "secondary"}>
                        {summarizationSettings?.healthy ? "online" : "offline"}
                      </Badge>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Installed models:</span>{" "}
                      {summarizationSettings?.models.length ?? 0}
                    </div>
                    {summarizationSettings?.health_error && (
                      <p className="md:col-span-2 text-destructive">{summarizationSettings.health_error}</p>
                    )}
                    {summarizationSettings?.pull_status.status !== "idle" && (
                      <p className="md:col-span-2">
                        <span className="text-muted-foreground">Pull:</span>{" "}
                        {summarizationSettings?.pull_status.model} · {summarizationSettings?.pull_status.status}
                        {summarizationSettings?.pull_status.message ? ` · ${summarizationSettings.pull_status.message}` : ""}
                        {summarizationSettings?.pull_status.error ? ` · ${summarizationSettings.pull_status.error}` : ""}
                      </p>
                    )}
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="flex items-center justify-between gap-4 rounded-md border bg-muted/20 p-3">
                      <div>
                        <Label>Enable summaries</Label>
                        <p className="text-xs text-muted-foreground">Uses only the local Ollama service.</p>
                      </div>
                      <Switch
                        checked={summarizationForm.enabled}
                        onCheckedChange={(checked) => updateSummarizationField("enabled", checked)}
                      />
                    </div>
                    <div className="flex items-center justify-between gap-4 rounded-md border bg-muted/20 p-3">
                      <div>
                        <Label>Auto-summarize</Label>
                        <p className="text-xs text-muted-foreground">Queue a summary after each successful transcription.</p>
                      </div>
                      <Switch
                        checked={summarizationForm.auto_summarize}
                        onCheckedChange={(checked) => updateSummarizationField("auto_summarize", checked)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Ollama URL</Label>
                      <Input
                        value={summarizationForm.ollama_base_url}
                        onChange={(event) => updateSummarizationField("ollama_base_url", event.currentTarget.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Summary model</Label>
                      <Select
                        value={summarizationForm.selected_model || "none"}
                        onValueChange={(value) => updateSummarizationField("selected_model", value === "none" ? "" : value)}
                      >
                        <SelectTrigger><SelectValue placeholder="Select Ollama model" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">No model selected</SelectItem>
                          {(summarizationSettings?.models ?? []).map((model) => (
                            <SelectItem key={model.name} value={model.name}>
                              {model.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
                    <div className="space-y-2">
                      <Label>Pull Ollama model</Label>
                      <Select
                        value={pullModel}
                        onValueChange={setPullModel}
                      >
                        <SelectTrigger><SelectValue placeholder="Choose model to pull" /></SelectTrigger>
                        <SelectContent>
                          {(summarizationSettings?.recommended_models ?? []).map((model) => (
                            <SelectItem key={model} value={model}>
                              {model}
                            </SelectItem>
                          ))}
                          <SelectItem value="gemma3:1b">gemma3:1b</SelectItem>
                          <SelectItem value="llama3.2:1b">llama3.2:1b</SelectItem>
                          <SelectItem value="custom">Custom model name</SelectItem>
                        </SelectContent>
                      </Select>
                      {pullModel === "custom" && (
                        <Input
                          value={customPullModel}
                          onChange={(event) => setCustomPullModel(event.currentTarget.value)}
                          placeholder="model:tag"
                        />
                      )}
                      <div className="flex flex-wrap gap-2">
                        {(summarizationSettings?.models ?? []).map((model) => (
                          <Badge key={model.name} variant="outline">
                            {model.name}
                          </Badge>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Recommended for Pi 5: qwen2.5:3b for quality, qwen2.5:1.5b for lower memory.
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={pullSummarizationModelMutation.isPending || !selectedPullModel}
                      onClick={() => pullSummarizationModelMutation.mutate()}
                    >
                      {pullSummarizationModelMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Download className="mr-2 h-4 w-4" />
                      )}
                      Pull Model
                    </Button>
                  </div>

                  <div className="space-y-2">
                    <Label>Summary system prompt</Label>
                    <Textarea
                      className="min-h-24"
                      value={summarizationForm.system_prompt}
                      onChange={(event) => updateSummarizationField("system_prompt", event.currentTarget.value)}
                    />
                  </div>

                  <Button
                    type="button"
                    disabled={updateSummarizationMutation.isPending}
                    onClick={() => updateSummarizationMutation.mutate()}
                  >
                    {updateSummarizationMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" />
                    )}
                    Save Summarization
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Bot className="h-4 w-4" />
                    Telegram Bot
                  </CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Receive audio from allowed Telegram users and send back finished JSON transcriptions.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={testTelegramMutation.isPending}
                    onClick={() => testTelegramMutation.mutate()}
                  >
                    {testTelegramMutation.isPending && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                    Test Bot
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={restartTelegramMutation.isPending}
                    onClick={() => restartTelegramMutation.mutate()}
                  >
                    {restartTelegramMutation.isPending && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                    Restart
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {telegramSettingsLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="grid gap-3 rounded-md border bg-muted/20 p-3 text-sm md:grid-cols-2">
                    <div>
                      <span className="text-muted-foreground">State:</span>{" "}
                      <Badge variant={telegramSettings?.status.running ? "default" : "secondary"}>
                        {telegramSettings?.status.running ? "polling" : "stopped"}
                      </Badge>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Token:</span>{" "}
                      {telegramSettings?.token_configured ? telegramSettings.token_preview : "not configured"}
                    </div>
                    <div>
                      <span className="text-muted-foreground">Last poll:</span>{" "}
                      {telegramSettings?.status.last_poll_at ? formatDateLocal(telegramSettings.status.last_poll_at) : "never"}
                    </div>
                    <div>
                      <span className="text-muted-foreground">Offset:</span>{" "}
                      {telegramSettings?.status.update_offset ?? "none"}
                    </div>
                    {telegramSettings?.status.last_error && (
                      <p className="md:col-span-2 text-destructive">{telegramSettings.status.last_error}</p>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-4 rounded-md border bg-muted/20 p-3">
                    <div>
                      <Label>Enable Telegram bot</Label>
                      <p className="text-xs text-muted-foreground">Long polling starts after settings are saved.</p>
                    </div>
                    <Switch
                      checked={telegramForm.enabled}
                      onCheckedChange={(checked) => setTelegramForm((current) => ({ ...current, enabled: checked }))}
                    />
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Bot token</Label>
                      <Input
                        type="password"
                        value={telegramForm.bot_token}
                        onChange={(event) => setTelegramForm((current) => ({ ...current, bot_token: event.target.value }))}
                        placeholder={telegramSettings?.token_configured ? "Leave empty to keep current token" : "123456:ABC..."}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Proxy URL</Label>
                      <Input
                        value={telegramForm.proxy_url}
                        onChange={(event) => setTelegramForm((current) => ({ ...current, proxy_url: event.target.value }))}
                        placeholder="http://host.docker.internal:10809"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Default model</Label>
                      <Select
                        value={telegramForm.default_model_id || "none"}
                        onValueChange={(value) => setTelegramForm((current) => ({
                          ...current,
                          default_model_id: value === "none" ? "" : value,
                        }))}
                      >
                        <SelectTrigger><SelectValue placeholder="Select installed model" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">No model selected</SelectItem>
                          {installedModels.map((model) => (
                            <SelectItem key={model.id} value={String(model.id)}>
                              {model.display_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {selectedTelegramModel && (
                        <p className="text-xs text-muted-foreground">
                          {selectedTelegramModel.provider} · {selectedTelegramModel.variant}
                        </p>
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label>Default language</Label>
                      <Select
                        value={telegramForm.default_language}
                        onValueChange={(value) => setTelegramForm((current) => ({ ...current, default_language: value }))}
                      >
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="auto">Auto</SelectItem>
                          <SelectItem value="en">English</SelectItem>
                          <SelectItem value="ru">Russian</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="space-y-3 rounded-md border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <Label>Split Telegram transcriptions</Label>
                        <p className="text-xs text-muted-foreground">
                          Telegram jobs can be split into chunks and claimed by capable workers as they become free.
                        </p>
                      </div>
                      <Switch
                        checked={telegramForm.split_enabled}
                        onCheckedChange={(checked) =>
                          setTelegramForm((current) => ({ ...current, split_enabled: checked }))
                        }
                      />
                    </div>
                    {telegramForm.split_enabled && (
                      <div className="space-y-2">
                        <p className="text-xs font-medium text-muted-foreground">
                          Split workers
                        </p>
                        <div className="grid gap-2 sm:grid-cols-2">
                          {workers
                            .filter((worker) => worker.accepted && !worker.is_deleted)
                            .map((worker) => (
                              <label
                                key={worker.id}
                                className="flex items-center gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm"
                              >
                                <input
                                  type="checkbox"
                                  checked={telegramForm.split_worker_ids.includes(worker.id)}
                                  onChange={() => toggleTelegramSplitWorker(worker.id)}
                                />
                                <span className="min-w-0 truncate">{worker.display_name || worker.name}</span>
                              </label>
                            ))}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          Leave all unchecked for automatic capable workers, or choose at least two workers.
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <Label>Allowed Telegram users</Label>
                        <p className="text-xs text-muted-foreground">Map Telegram user IDs to ASR UI file owners.</p>
                      </div>
                      <Button type="button" variant="outline" size="sm" onClick={addTelegramMapping}>
                        <Plus className="mr-2 h-3 w-3" />
                        Add User
                      </Button>
                    </div>
                    {telegramForm.allowed_users.length === 0 ? (
                      <p className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
                        No Telegram users allowed.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {telegramForm.allowed_users.map((mapping, index) => (
                          <div key={index} className="grid gap-2 rounded-md border p-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
                            <div className="space-y-2">
                              <Label>Telegram user ID</Label>
                              <Input
                                type="number"
                                value={mapping.telegram_user_id || ""}
                                onChange={(event) => updateTelegramMapping(
                                  index,
                                  "telegram_user_id",
                                  Number(event.currentTarget.value)
                                )}
                              />
                            </div>
                            <div className="space-y-2">
                              <Label>ASR UI user</Label>
                              <Select
                                value={mapping.app_user_id ? String(mapping.app_user_id) : "none"}
                                onValueChange={(value) => updateTelegramMapping(
                                  index,
                                  "app_user_id",
                                  value === "none" ? 0 : Number(value)
                                )}
                              >
                                <SelectTrigger><SelectValue placeholder="Select user" /></SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="none">No user selected</SelectItem>
                                  {users.map((item) => (
                                    <SelectItem key={item.id} value={String(item.id)}>
                                      {item.username}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <Button
                              type="button"
                              variant="outline"
                              size="icon"
                              onClick={() => removeTelegramMapping(index)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <Button
                    type="button"
                    disabled={updateTelegramMutation.isPending}
                    onClick={() => updateTelegramMutation.mutate()}
                  >
                    {updateTelegramMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" />
                    )}
                    Save Telegram Settings
                  </Button>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Terminal className="h-4 w-4" />
                    Whisper CLI Parameters
                  </CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Runtime parameters used for newly queued transcription jobs.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={resetWhisperMutation.isPending}
                  onClick={() => resetWhisperMutation.mutate()}
                >
                  {resetWhisperMutation.isPending ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : (
                    <RotateCcw className="mr-2 h-3 w-3" />
                  )}
                  Reset to Defaults
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              {whisperSettingsLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  <div className="space-y-2">
                    <Label>Threads (`-t`)</Label>
                    <Input
                      type="number"
                      min={1}
                      max={64}
                      value={whisperForm.whisper_threads}
                      onChange={(event) => updateWhisperField("whisper_threads", Number(event.currentTarget.value))}
                    />
                    <p className="text-xs text-muted-foreground">
                      Default: {whisperSettings?.defaults?.whisper_threads ?? EMPTY_WHISPER_SETTINGS.whisper_threads}
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Max context (`-mc`)</Label>
                    <Input
                      type="number"
                      min={-1}
                      max={8192}
                      value={whisperForm.whisper_max_context}
                      onChange={(event) => updateWhisperField("whisper_max_context", Number(event.currentTarget.value))}
                    />
                    <p className="text-xs text-muted-foreground">
                      `0` prevents hallucinated context from carrying across windows.
                    </p>
                  </div>
                  <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <Label>Use GPU</Label>
                      <Switch
                        checked={whisperForm.whisper_use_gpu}
                        onCheckedChange={(checked) => updateWhisperField("whisper_use_gpu", checked)}
                      />
                    </div>
                    <p className="text-xs text-muted-foreground">Off adds `-ng`.</p>
                  </div>
                  <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <Label>Flash attention</Label>
                      <Switch
                        checked={whisperForm.whisper_flash_attn}
                        onCheckedChange={(checked) => updateWhisperField("whisper_flash_attn", checked)}
                      />
                    </div>
                    <p className="text-xs text-muted-foreground">Off adds `-nfa`.</p>
                  </div>
                  <div className="space-y-3 rounded-md border bg-muted/20 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <Label>Suppress non-speech</Label>
                      <Switch
                        checked={whisperForm.whisper_suppress_non_speech}
                        onCheckedChange={(checked) => updateWhisperField("whisper_suppress_non_speech", checked)}
                      />
                    </div>
                    <p className="text-xs text-muted-foreground">On adds `-sns`.</p>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Suppress regex</Label>
                    <Input
                      value={whisperForm.whisper_suppress_regex ?? ""}
                      onChange={(event) => updateWhisperField("whisper_suppress_regex", event.currentTarget.value)}
                      placeholder="Optional --suppress-regex"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Transcript cleanup regex</Label>
                    <Input
                      value={whisperForm.transcript_filter_regex ?? ""}
                      onChange={(event) => updateWhisperField("transcript_filter_regex", event.currentTarget.value)}
                      placeholder="Optional post-processing filter"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>CLI preview</Label>
                  <Textarea
                    className="min-h-24 font-mono text-xs"
                    readOnly
                    value={whisperCliPreview}
                  />
                </div>

                <Button
                  type="button"
                  disabled={updateWhisperMutation.isPending}
                  onClick={() => updateWhisperMutation.mutate()}
                >
                  {updateWhisperMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="mr-2 h-4 w-4" />
                  )}
                  Save Parameters
                </Button>
              </>
            )}
          </CardContent>
        </Card>
        </>
      )}
    </div>
  )
}
