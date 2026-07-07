import { Ban, Brain, Copy, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { formatDateTimeLocal } from "@/lib/datetime"
import { summaryRuntime } from "@/lib/jobs"
import type { TranscriptionJob } from "@/types"

interface SummaryPanelProps {
  job: TranscriptionJob
  onGenerate: (jobId: number) => void
  onCancel: (jobId: number) => void
  generating: boolean
  cancelling: boolean
}

export function SummaryPanel({ job, onGenerate, onCancel, generating, cancelling }: SummaryPanelProps) {
  const active = job.summary_status === "queued" || job.summary_status === "running"
  return (
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
            disabled={generating || active}
            onClick={() => onGenerate(job.id)}
          >
            {generating ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : <Brain className="mr-2 h-3 w-3" />}
            {job.summary_text ? "Regenerate" : "Generate"}
          </Button>
          {active && (
            <Button type="button" variant="outline" size="sm" disabled={cancelling} onClick={() => onCancel(job.id)}>
              {cancelling ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : <Ban className="mr-2 h-3 w-3" />}
              Cancel
            </Button>
          )}
        </div>
      </div>
      {job.summary_error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
          {job.summary_error}
        </p>
      )}
      {job.summary_text ? (
        <div className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-sm leading-relaxed">
          {job.summary_text}
        </div>
      ) : (
        <p className="rounded-md bg-background p-3 text-sm text-muted-foreground">
          {active ? "Summary is being generated." : "No summary generated yet."}
        </p>
      )}
    </div>
  )
}
