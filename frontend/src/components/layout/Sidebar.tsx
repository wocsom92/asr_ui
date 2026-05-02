import { NavLink } from "react-router-dom"
import {
  AudioLines,
  LayoutDashboard,
  ListChecks,
  FolderKanban,
  Users,
  Settings,
  FileAudio,
  Cpu,
  ServerCog,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { FRONTEND_VERSION } from "@/lib/version"
import { useAuthStore } from "@/stores/auth"
import { Separator } from "@/components/ui/separator"

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/files", label: "Audio Files", icon: FileAudio },
  { to: "/jobs", label: "Jobs", icon: ListChecks },
  { to: "/transcriptions", label: "Transcriptions", icon: AudioLines },
  { to: "/projects", label: "Projects", icon: FolderKanban },
]

const adminItems = [
  { to: "/models", label: "Models", icon: Cpu },
  { to: "/workers", label: "Workers", icon: ServerCog },
  { to: "/users", label: "Users", icon: Users },
]

const bottomItems = [
  { to: "/settings", label: "Settings", icon: Settings },
]

export function Sidebar() {
  const user = useAuthStore((s) => s.user)

  return (
    <aside className="hidden md:flex md:w-64 md:flex-col md:fixed md:inset-y-0 border-r bg-sidebar">
      <div className="flex h-16 items-center gap-2 px-6 border-b">
        <AudioLines className="h-6 w-6 text-sidebar-primary" />
        <span className="text-lg font-bold text-sidebar-foreground">
          ASR UI
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto py-4 px-3">
        <ul className="space-y-1">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                  )
                }
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>

        {user?.role === "admin" && (
          <>
            <Separator className="my-4" />
            <p className="px-3 mb-2 text-xs font-semibold text-sidebar-foreground/60 uppercase tracking-wider">
              Admin
            </p>
            <ul className="space-y-1">
              {adminItems.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                        isActive
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                      )
                    }
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </>
        )}

        <Separator className="my-4" />
        <ul className="space-y-1">
          {bottomItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                  )
                }
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t px-4 py-3">
        <p className="text-xs text-sidebar-foreground/50">
          v{FRONTEND_VERSION}
        </p>
      </div>
    </aside>
  )
}
