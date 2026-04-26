import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { AudioLines } from "lucide-react"
import api from "@/api/client"
import { useAuthStore } from "@/stores/auth"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export default function Login() {
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)
  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError("")
    setLoading(true)
    try {
      if (isRegister) {
        await api.post("/auth/register", { username, email, password })
      }
      const { data } = await api.post("/auth/login", { username, password })
      setUser(data.user)
      navigate("/")
    } catch (err: any) {
      setError(err.response?.data?.detail || "Authentication failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary">
            <AudioLines className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-2xl">ASR UI</CardTitle>
          <CardDescription>
            {isRegister ? "Create the first administrator account" : "Sign in to your transcription workspace"}
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            {isRegister && (
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-4">
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Please wait..." : isRegister ? "Create Admin" : "Sign In"}
            </Button>
            <Button type="button" variant="link" onClick={() => setIsRegister(!isRegister)}>
              {isRegister ? "Already have an account? Sign in" : "Set up first admin account"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}
