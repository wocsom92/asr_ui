import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import { useAuthStore } from "@/stores/auth"
import type { Project } from "@/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

export default function Settings() {
  const qc = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [projectName, setProjectName] = useState("")
  const [projectDescription, setProjectDescription] = useState("")
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null)
  const [editingProjectName, setEditingProjectName] = useState("")
  const [editingProjectDescription, setEditingProjectDescription] = useState("")

  const { data: projects = [], isLoading: projectsLoading } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.get("/projects").then((r) => r.data),
  })

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

  const createProjectMutation = useMutation({
    mutationFn: () =>
      api.post("/projects", {
        name: projectName,
        description: projectDescription,
      }),
    onSuccess: () => {
      setProjectName("")
      setProjectDescription("")
      qc.invalidateQueries({ queryKey: ["projects"] })
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
      qc.invalidateQueries({ queryKey: ["projects"] })
      qc.invalidateQueries({ queryKey: ["files"] })
      qc.invalidateQueries({ queryKey: ["transcriptions"] })
      toast.success("Project updated")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Could not update project"),
  })

  const deleteProjectMutation = useMutation({
    mutationFn: (projectId: number) => api.delete(`/projects/${projectId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] })
      qc.invalidateQueries({ queryKey: ["files"] })
      qc.invalidateQueries({ queryKey: ["transcriptions"] })
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
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Account details and password.</p>
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

      <Card>
        <CardHeader>
          <CardTitle>Projects</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <form
            className="space-y-3"
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
                className="min-h-20"
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

          <div className="space-y-3">
            {projectsLoading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : projects.length === 0 ? (
              <p className="rounded-md border bg-muted/30 p-4 text-sm text-muted-foreground">
                No projects yet.
              </p>
            ) : (
              projects.map((project) => (
                <div key={project.id} className="rounded-md border p-3">
                  {editingProjectId === project.id ? (
                    <form
                      className="space-y-3"
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
                        className="min-h-20"
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
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{project.name}</p>
                        {project.description && (
                          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                            {project.description}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <Button size="icon" variant="outline" onClick={() => startEditingProject(project)}>
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          size="icon"
                          variant="outline"
                          className="border-destructive/40 text-destructive hover:bg-destructive/10"
                          onClick={() => {
                            if (window.confirm("Delete this project? Audio files and transcriptions will become Unassigned.")) {
                              deleteProjectMutation.mutate(project.id)
                            }
                          }}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
