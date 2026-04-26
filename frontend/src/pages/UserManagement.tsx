import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import api from "@/api/client"
import type { User } from "@/types"
import { useAuthStore } from "@/stores/auth"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { formatDateLocal } from "@/lib/datetime"

export default function UserManagement() {
  const currentUser = useAuthStore((s) => s.user)
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<"admin" | "user">("user")

  const { data: users = [], isLoading } = useQuery<User[]>({
    queryKey: ["users"],
    queryFn: () => api.get("/users/").then((r) => r.data),
    enabled: currentUser?.role === "admin",
  })

  const closeDialog = () => setOpen(false)
  const openCreate = () => {
    setEditing(null)
    setUsername("")
    setEmail("")
    setPassword("")
    setRole("user")
    setOpen(true)
  }
  const openEdit = (user: User) => {
    setEditing(user)
    setUsername(user.username)
    setEmail(user.email)
    setPassword("")
    setRole(user.role)
    setOpen(true)
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      if (editing) {
        const payload: any = { email, role }
        if (password) payload.password = password
        return api.put(`/users/${editing.id}`, payload)
      }
      return api.post("/users/", { username, email, password, role })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] })
      closeDialog()
      toast.success("User saved")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "User save failed"),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/users/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] })
      toast.success("User deleted")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Delete failed"),
  })

  if (currentUser?.role !== "admin") {
    return <div className="py-12 text-center text-muted-foreground">Admin access required.</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground">Create accounts and assign roles.</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> Add User
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <div className="hidden overflow-hidden rounded-lg border md:block">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="p-3 text-left font-medium">User</th>
                  <th className="p-3 text-left font-medium">Email</th>
                  <th className="p-3 text-left font-medium">Role</th>
                  <th className="p-3 text-left font-medium">Joined</th>
                  <th className="p-3 text-left font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="p-3 font-medium">{user.username}</td>
                    <td className="p-3 text-muted-foreground">{user.email}</td>
                    <td className="p-3"><Badge>{user.role}</Badge></td>
                    <td className="p-3 text-muted-foreground">{formatDateLocal(user.created_at)}</td>
                    <td className="p-3">
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => openEdit(user)}>
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button variant="outline" size="sm" disabled={user.id === currentUser.id} onClick={() => deleteMutation.mutate(user.id)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-3 md:hidden">
            {users.map((user) => (
              <Card key={user.id}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">{user.username}</CardTitle>
                    <Badge>{user.role}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="text-sm text-muted-foreground">{user.email}</p>
                  <p className="text-xs text-muted-foreground">{formatDateLocal(user.created_at)}</p>
                  <div className="flex gap-2">
                    <Button className="flex-1" variant="outline" onClick={() => openEdit(user)}>
                      <Pencil className="mr-2 h-4 w-4" /> Edit
                    </Button>
                    <Button variant="outline" size="icon" disabled={user.id === currentUser.id} onClick={() => deleteMutation.mutate(user.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "Edit user" : "Add user"}</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              saveMutation.mutate()
            }}
          >
            {!editing && (
              <div className="space-y-2">
                <Label>Username</Label>
                <Input value={username} onChange={(e) => setUsername(e.target.value)} required />
              </div>
            )}
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label>{editing ? "New password" : "Password"}</Label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required={!editing} />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={role} onValueChange={(value: "admin" | "user") => setRole(value)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">User</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={saveMutation.isPending}>
                {saveMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
