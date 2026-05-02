import { BrowserRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useEffect } from "react"
import { Toaster } from "sonner"
import { useAuthStore } from "@/stores/auth"
import { AppShell } from "@/components/layout/AppShell"
import Dashboard from "@/pages/Dashboard"
import Files from "@/pages/Files"
import Jobs from "@/pages/Jobs"
import Login from "@/pages/Login"
import Models from "@/pages/Models"
import Projects from "@/pages/Projects"
import Settings from "@/pages/Settings"
import Transcriptions from "@/pages/Transcriptions"
import UserManagement from "@/pages/UserManagement"
import Workers from "@/pages/Workers"

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function AuthLoader({ children }: { children: React.ReactNode }) {
  const fetchUser = useAuthStore((s) => s.fetchUser)
  useEffect(() => {
    fetchUser()
  }, [fetchUser])
  return <>{children}</>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthLoader>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<AppShell />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/files" element={<Files />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/transcriptions" element={<Transcriptions />} />
              <Route path="/projects" element={<Projects />} />
              <Route path="/models" element={<Models />} />
              <Route path="/users" element={<UserManagement />} />
              <Route path="/workers" element={<Workers />} />
              <Route path="/settings" element={<Settings />} />
            </Route>
          </Routes>
          <Toaster richColors position="top-right" />
        </AuthLoader>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
