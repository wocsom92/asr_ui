import { Folder } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Project } from "@/types"

const PROJECT_COLORS = [
  "border-sky-200 bg-sky-50 text-sky-800",
  "border-emerald-200 bg-emerald-50 text-emerald-800",
  "border-amber-200 bg-amber-50 text-amber-900",
  "border-blue-200 bg-blue-50 text-blue-800",
  "border-cyan-200 bg-cyan-50 text-cyan-800",
  "border-teal-200 bg-teal-50 text-teal-800",
  "border-lime-200 bg-lime-50 text-lime-900",
  "border-stone-200 bg-stone-50 text-stone-700",
]

function projectColor(project: Project | null | undefined): string {
  if (!project) return "border-slate-200 bg-slate-50 text-slate-600"
  const seed = `${project.id}:${project.name}`
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0
  }
  return PROJECT_COLORS[hash % PROJECT_COLORS.length]
}

export function ProjectBadge({
  project,
  className,
}: {
  project: Project | null | undefined
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium shadow-sm",
        projectColor(project),
        className
      )}
      title={project?.name ?? "Unassigned"}
    >
      <Folder className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{project?.name ?? "Unassigned"}</span>
    </span>
  )
}
