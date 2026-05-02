import { useEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronUp, Clock, Loader2, Play, Search } from "lucide-react"

import api from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatDuration } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { TranscriptionJob } from "@/types"

interface TranscriptSegment {
  start: number
  end: number
  text: string
}

interface TranscriptAudioPlayerProps {
  job: TranscriptionJob
  source?: "auto" | "partial" | "final"
  title?: string
}

interface TranscriptSearchMatch {
  segmentIndex: number
  start: number
  end: number
}

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00"
  const total = Math.floor(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remaining = total % 60
  const mm = hours > 0 ? String(minutes).padStart(2, "0") : String(minutes)
  const ss = String(remaining).padStart(2, "0")
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

function findSegmentMatches(
  segments: TranscriptSegment[],
  query: string
): TranscriptSearchMatch[] {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return []

  return segments.flatMap((segment, segmentIndex) => {
    const haystack = segment.text.toLocaleLowerCase()
    const matches: TranscriptSearchMatch[] = []
    let index = haystack.indexOf(needle)
    while (index !== -1) {
      matches.push({ segmentIndex, start: index, end: index + needle.length })
      index = haystack.indexOf(needle, index + needle.length)
    }
    return matches
  })
}

function renderSegmentText(
  text: string,
  matches: TranscriptSearchMatch[],
  activeMatchIndex: number,
  segmentIndex: number
) {
  const segmentMatches = matches
    .map((match, globalIndex) => ({ ...match, globalIndex }))
    .filter((match) => match.segmentIndex === segmentIndex)

  if (segmentMatches.length === 0) return text

  return segmentMatches.map((match, index) => {
    const previous = segmentMatches[index - 1]
    const plainStart = previous ? previous.end : 0
    const active = match.globalIndex === activeMatchIndex
    return (
      <span key={`${match.start}-${match.end}`}>
        {text.slice(plainStart, match.start)}
        <mark
          className={
            active
              ? "rounded bg-primary px-0.5 text-primary-foreground"
              : "rounded bg-amber-200 px-0.5 text-amber-950"
          }
        >
          {text.slice(match.start, match.end)}
        </mark>
        {index === segmentMatches.length - 1 ? text.slice(match.end) : null}
      </span>
    )
  })
}

export function TranscriptAudioPlayer({
  job,
  source = "auto",
  title = "Live transcript",
}: TranscriptAudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const activeSegmentRef = useRef<HTMLButtonElement | null>(null)
  const activeSearchRef = useRef<HTMLButtonElement | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(job.audio_file?.duration_seconds ?? 0)
  const [seekSeconds, setSeekSeconds] = useState("")
  const [isPlaying, setIsPlaying] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [activeMatchIndex, setActiveMatchIndex] = useState(0)

  const audioUrl = `/api/v1/files/${job.audio_file_id}/audio`
  const hasPartial = Boolean(job.partial_transcript_text || job.partial_transcript_json)
  const { data: segments = [], isLoading } = useQuery<TranscriptSegment[]>({
    queryKey: ["transcription-segments", job.id, source, job.partial_updated_at],
    queryFn: () => api.get(`/transcriptions/${job.id}/segments`, { params: { source } }).then((r) => r.data),
    enabled: job.status === "succeeded" || hasPartial,
    refetchInterval: job.status === "running" ? 2000 : false,
    retry: false,
  })

  const activeIndex = useMemo(() => {
    if (!segments.length) return -1
    const direct = segments.findIndex(
      (segment) => currentTime >= segment.start && currentTime <= segment.end
    )
    if (direct !== -1) return direct
    for (let index = segments.length - 1; index >= 0; index -= 1) {
      if (currentTime >= segments[index].start) return index
    }
    return -1
  }, [currentTime, segments])

  const activeSegment = activeIndex >= 0 ? segments[activeIndex] : null
  const searchMatches = useMemo(
    () => findSegmentMatches(segments, searchQuery),
    [segments, searchQuery]
  )
  const activeSearchMatch = searchMatches[activeMatchIndex]

  useEffect(() => {
    setActiveMatchIndex(0)
  }, [searchQuery, segments])

  useEffect(() => {
    if (!isPlaying || !activeSegmentRef.current) return
    activeSegmentRef.current.scrollIntoView({ block: "nearest" })
  }, [activeIndex, isPlaying])

  useEffect(() => {
    if (!activeSearchMatch || !activeSearchRef.current) return
    activeSearchRef.current.scrollIntoView({ block: "center" })
  }, [activeSearchMatch])

  const seekTo = (seconds: number, play = true) => {
    const audio = audioRef.current
    if (!audio) return

    const bounded = Math.max(0, Math.min(seconds, duration || seconds))
    audio.currentTime = bounded
    setCurrentTime(bounded)
    if (play) void audio.play()
  }

  const jumpToInput = () => {
    const seconds = Number(seekSeconds)
    if (!Number.isFinite(seconds)) return
    seekTo(seconds, true)
  }

  const jumpToSearchMatch = (matchIndex: number) => {
    const match = searchMatches[matchIndex]
    if (!match) return
    setActiveMatchIndex(matchIndex)
    seekTo(segments[match.segmentIndex].start, false)
  }

  const moveSearchMatch = (direction: 1 | -1) => {
    if (!searchMatches.length) return
    const nextIndex = (activeMatchIndex + direction + searchMatches.length) % searchMatches.length
    jumpToSearchMatch(nextIndex)
  }

  return (
    <div className="space-y-4 rounded-md border bg-muted/20 p-3">
      <div className="space-y-3">
        <audio
          ref={audioRef}
          className="w-full"
          controls
          preload="metadata"
          src={audioUrl}
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || duration)}
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
        />
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{formatClock(currentTime)}</span>
              <span>{formatDuration(duration)}</span>
            </div>
            <Input
              type="range"
              min={0}
              max={Math.max(1, duration || 1)}
              step="0.1"
              value={Math.min(currentTime, duration || currentTime)}
              onChange={(event) => seekTo(Number(event.currentTarget.value), false)}
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Clock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="w-32 pl-9"
                inputMode="decimal"
                placeholder="Seconds"
                value={seekSeconds}
                onChange={(event) => setSeekSeconds(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") jumpToInput()
                }}
              />
            </div>
            <Button type="button" onClick={jumpToInput}>
              <Play className="mr-2 h-4 w-4" />
              Jump
            </Button>
          </div>
        </div>
      </div>

      <div className="rounded-md border bg-background">
        <div className="space-y-3 border-b px-3 py-3">
          <div className="text-sm font-medium">
            {activeSegment ? activeSegment.text : title}
          </div>
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="h-9 pl-9"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault()
                    moveSearchMatch(event.shiftKey ? -1 : 1)
                  }
                }}
                placeholder="Search timed transcript"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="min-w-24 text-sm text-muted-foreground">
                {searchQuery.trim()
                  ? searchMatches.length > 0
                    ? `${activeMatchIndex + 1} / ${searchMatches.length}`
                    : "No matches"
                  : "Search"}
              </span>
              <Button
                type="button"
                variant="outline"
                size="icon"
                disabled={!searchMatches.length}
                onClick={() => moveSearchMatch(-1)}
                title="Previous match"
              >
                <ChevronUp className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                disabled={!searchMatches.length}
                onClick={() => moveSearchMatch(1)}
                title="Next match"
              >
                <ChevronDown className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
        <div className="max-h-72 overflow-y-auto p-2">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading timed transcript
            </div>
          ) : segments.length > 0 ? (
            <div className="space-y-1">
              {segments.map((segment, index) => {
                const active = index === activeIndex
                const searchActive = activeSearchMatch?.segmentIndex === index
                return (
                  <button
                    key={`${segment.start}-${index}`}
                    ref={(element) => {
                      if (active) activeSegmentRef.current = element
                      if (searchActive) activeSearchRef.current = element
                    }}
                    type="button"
                    className={cn(
                      "grid w-full grid-cols-[4.5rem_minmax(0,1fr)] gap-3 rounded px-2 py-2 text-left text-sm transition-colors",
                      active
                        ? "bg-primary text-primary-foreground"
                        : searchActive
                          ? "bg-amber-50 ring-1 ring-amber-300 hover:bg-amber-100"
                          : "hover:bg-muted"
                    )}
                    onClick={() => seekTo(segment.start, true)}
                  >
                    <span className={cn("text-xs", active ? "text-primary-foreground/80" : "text-muted-foreground")}>
                      {formatClock(segment.start)}
                    </span>
                    <span>{renderSegmentText(segment.text, searchMatches, activeMatchIndex, index)}</span>
                  </button>
                )
              })}
            </div>
          ) : (
            <p className="whitespace-pre-wrap p-2 text-sm text-muted-foreground">
              {source === "partial"
                ? job.partial_transcript_text || "Partial timed transcript is not available yet."
                : job.transcript_text || job.partial_transcript_text || "Timed transcript is not available for this transcription."}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
