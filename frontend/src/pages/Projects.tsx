import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileAudio, Folder, FolderOpen, Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"

import api from "@/api/client"
import { useConfirm } from "@/components/ConfirmDialog"
import { ProjectBadge } from "@/components/ProjectBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type { Project } from "@/types"

export default function Projects() {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const [projectName, setProjectName] = useState("")
  const [projectDescription, setProjectDescription] = useState("")
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null)
  const [editingProjectName, setEditingProjectName] = useState("")
  const [editingProjectDescription, setEditingProjectDescription] = useState("")

  const { data: projects = [], isLoading } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.get("/projects").then((r) => r.data),
  })

  const invalidateProjectViews = () => {
    qc.invalidateQueries({ queryKey: ["projects"] })
    qc.invalidateQueries({ queryKey: ["files"] })
    qc.invalidateQueries({ queryKey: ["transcriptions"] })
  }

  const createProjectMutation = useMutation({
    mutationFn: () =>
      api.post("/projects", {
        name: projectName,
        description: projectDescription,
      }),
    onSuccess: () => {
      setProjectName("")
      setProjectDescription("")
      invalidateProjectViews()
      toast.success("Project created")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not create project"),
  })

  const updateProjectMutation = useMutation({
    mutationFn: () =>
      api.patch(`/projects/${editingProjectId}`, {
        name: editingProjectName,
        description: editingProjectDescription,
      }),
    onSuccess: () => {
      setEditingProjectId(null)
      invalidateProjectViews()
      toast.success("Project updated")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not update project"),
  })

  const deleteProjectMutation = useMutation({
    mutationFn: (projectId: number) => api.delete(`/projects/${projectId}`),
    onSuccess: () => {
      invalidateProjectViews()
      toast.success("Project deleted")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not delete project"),
  })

  const startEditingProject = (project: Project) => {
    setEditingProjectId(project.id)
    setEditingProjectName(project.name)
    setEditingProjectDescription(project.description || "")
  }

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Projects</h1>
        <p className="text-muted-foreground">Create folders for audio files and their transcriptions.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>New Project</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault()
                createProjectMutation.mutate()
              }}
            >
              <div className="space-y-2">
                <Label>Project name</Label>
                <Input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  maxLength={100}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  className="min-h-28"
                  value={projectDescription}
                  onChange={(event) => setProjectDescription(event.target.value)}
                />
              </div>
              <Button type="submit" disabled={createProjectMutation.isPending}>
                {createProjectMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-2 h-4 w-4" />
                )}
                Create Project
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Folder Structure</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : projects.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 rounded-md border bg-muted/20 py-12 text-center">
                <Folder className="h-10 w-10 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">No projects yet.</p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-md border">
                <div className="flex items-center gap-3 border-b bg-muted/40 px-4 py-3 text-sm font-medium">
                  <FolderOpen className="h-4 w-4 text-muted-foreground" />
                  Projects
                </div>
                <div className="divide-y">
                  {projects.map((project) => (
                    <div key={project.id} className="bg-background">
                      {editingProjectId === project.id ? (
                        <form
                          className="space-y-3 p-4"
                          onSubmit={(event) => {
                            event.preventDefault()
                            updateProjectMutation.mutate()
                          }}
                        >
                          <Input
                            value={editingProjectName}
                            onChange={(event) => setEditingProjectName(event.target.value)}
                            maxLength={100}
                            required
                          />
                          <Textarea
                            className="min-h-24"
                            value={editingProjectDescription}
                            onChange={(event) => setEditingProjectDescription(event.target.value)}
                          />
                          <div className="flex flex-wrap gap-2">
                            <Button size="sm" type="submit" disabled={updateProjectMutation.isPending}>
                              {updateProjectMutation.isPending && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                              Save
                            </Button>
                            <Button size="sm" type="button" variant="outline" onClick={() => setEditingProjectId(null)}>
                              <X className="mr-2 h-3 w-3" />
                              Cancel
                            </Button>
                          </div>
                        </form>
                      ) : (
                        <div className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                          <div className="min-w-0">
                            <div className="flex min-w-0 items-center gap-3">
                              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-amber-50 text-amber-700">
                                <Folder className="h-5 w-5" />
                              </div>
                              <div className="min-w-0">
                                <ProjectBadge project={project} />
                                {project.description && (
                                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                                    {project.description}
                                  </p>
                                )}
                              </div>
                            </div>
                            <div className="ml-[3.25rem] mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                              <FileAudio className="h-3.5 w-3.5" />
                              Audio files and transcriptions inherit this folder
                            </div>
                          </div>
                          <div className="ml-[3.25rem] flex gap-2 sm:ml-0">
                            <Button size="icon" variant="outline" onClick={() => startEditingProject(project)}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="outline"
                              className="border-destructive/40 text-destructive hover:bg-destructive/10"
                              onClick={async () => {
                                const ok = await confirm({
                                  title: "Delete project?",
                                  description: "Audio files and transcriptions in this project will become Unassigned.",
                                  confirmLabel: "Delete",
                                  destructive: true,
                                })
                                if (ok) deleteProjectMutation.mutate(project.id)
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
