import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Plus, Save, Trash2, X } from "lucide-react"
import { toast } from "sonner"

import api from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

interface EditableSegment {
  start: number
  end: number
  text: string
  speaker?: string | null
}

interface TranscriptEditorProps {
  jobId: number
  onClose: () => void
}

function parseSeconds(value: string): number {
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : 0
}

export function TranscriptEditor({ jobId, onClose }: TranscriptEditorProps) {
  const qc = useQueryClient()
  const [segments, setSegments] = useState<EditableSegment[]>([])

  const { data: fetched = [], isLoading } = useQuery<EditableSegment[]>({
    queryKey: ["transcription-segments", jobId, "final", "edit"],
    queryFn: () => api.get(`/transcriptions/${jobId}/segments`, { params: { source: "final" } }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })

  useEffect(() => {
    setSegments(fetched.map((s) => ({ ...s })))
  }, [fetched])

  const speakers = useMemo(() => {
    const set = new Set<string>()
    segments.forEach((s) => {
      if (s.speaker) set.add(s.speaker)
    })
    return Array.from(set)
  }, [segments])

  const update = (index: number, patch: Partial<EditableSegment>) => {
    setSegments((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)))
  }
  const remove = (index: number) => setSegments((prev) => prev.filter((_, i) => i !== index))
  const addAfter = (index: number) => {
    setSegments((prev) => {
      const base = prev[index]
      const newSeg: EditableSegment = {
        start: base ? base.end : 0,
        end: base ? base.end : 0,
        text: "",
        speaker: base?.speaker ?? null,
      }
      const next = [...prev]
      next.splice(index + 1, 0, newSeg)
      return next
    })
  }

  const renameSpeaker = (from: string, to: string) => {
    const trimmed = to.trim()
    setSegments((prev) => prev.map((s) => (s.speaker === from ? { ...s, speaker: trimmed || null } : s)))
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      api
        .patch(`/transcriptions/${jobId}/segments`, {
          segments: segments
            .filter((s) => s.text.trim())
            .map((s) => ({
              start: s.start,
              end: Math.max(s.start, s.end),
              text: s.text.trim(),
              speaker: s.speaker?.trim() || null,
            })),
        })
        .then((r) => r.data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["transcription-segments", jobId] })
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      void qc.invalidateQueries({ queryKey: ["transcriptions", "detail"] })
      toast.success("Transcript updated and outputs regenerated")
      onClose()
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not save transcript"),
  })

  return (
    <div className="space-y-3 rounded-md border bg-muted/20 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Edit transcript</h3>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={onClose}>
            <X className="mr-2 h-3 w-3" /> Cancel
          </Button>
          <Button
            size="sm"
            disabled={saveMutation.isPending || segments.filter((s) => s.text.trim()).length === 0}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : <Save className="mr-2 h-3 w-3" />}
            Save & regenerate
          </Button>
        </div>
      </div>

      {speakers.length > 0 && (
        <div className="space-y-2 rounded-md border bg-background p-2">
          <p className="text-xs font-medium text-muted-foreground">Rename speakers</p>
          <div className="flex flex-wrap gap-2">
            {speakers.map((speaker) => (
              <Input
                key={speaker}
                defaultValue={speaker}
                className="h-8 w-40"
                onBlur={(e) => {
                  if (e.target.value.trim() !== speaker) renameSpeaker(speaker, e.target.value)
                }}
              />
            ))}
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading segments
        </div>
      ) : segments.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No timed segments available to edit.
        </p>
      ) : (
        <div className="max-h-[28rem] space-y-2 overflow-y-auto">
          {segments.map((segment, index) => (
            <div key={index} className="grid gap-2 rounded-md border bg-background p-2 sm:grid-cols-[5rem_5rem_8rem_minmax(0,1fr)_auto] sm:items-start">
              <Input
                className="h-8"
                inputMode="decimal"
                value={String(segment.start)}
                onChange={(e) => update(index, { start: parseSeconds(e.target.value) })}
                aria-label="Start seconds"
              />
              <Input
                className="h-8"
                inputMode="decimal"
                value={String(segment.end)}
                onChange={(e) => update(index, { end: parseSeconds(e.target.value) })}
                aria-label="End seconds"
              />
              <Input
                className="h-8"
                placeholder="Speaker"
                value={segment.speaker ?? ""}
                onChange={(e) => update(index, { speaker: e.target.value || null })}
                aria-label="Speaker"
              />
              <Textarea
                className="min-h-8"
                value={segment.text}
                onChange={(e) => update(index, { text: e.target.value })}
                aria-label="Segment text"
              />
              <div className="flex gap-1">
                <Button size="icon" variant="ghost" onClick={() => addAfter(index)} title="Add segment below">
                  <Plus className="h-4 w-4" />
                </Button>
                <Button size="icon" variant="ghost" className="text-destructive" onClick={() => remove(index)} title="Remove segment">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
