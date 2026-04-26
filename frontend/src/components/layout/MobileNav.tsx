import { NavLink } from "react-router-dom"
import {
  AudioLines,
  LayoutDashboard,
  ListChecks,
  Users,
  Settings,
  FileAudio,
  Cpu,
  Menu,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/stores/auth"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { useState } from "react"

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/files", label: "Audio Files", icon: FileAudio },
  { to: "/jobs", label: "Jobs", icon: ListChecks },
  { to: "/transcriptions", label: "Transcriptions", icon: AudioLines },
  { to: "/settings", label: "Settings", icon: Settings },
]

const adminItems = [
  { to: "/models", label: "Models", icon: Cpu },
  { to: "/users", label: "Users", icon: Users },
]

export function MobileNav() {
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" className="md:hidden">
          <Menu className="h-5 w-5" />
          <span className="sr-only">Toggle menu</span>
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-72 p-0">
        <SheetHeader className="px-6 py-4 border-b">
          <SheetTitle className="flex items-center gap-2">
            <AudioLines className="h-5 w-5" />
            ASR UI
          </SheetTitle>
        </SheetHeader>
        <nav className="py-4 px-3">
          <ul className="space-y-1">
            {navItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "text-foreground hover:bg-accent"
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
              <p className="px-3 mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Admin
              </p>
              <ul className="space-y-1">
                {adminItems.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      onClick={() => setOpen(false)}
                      className={({ isActive }) =>
                        cn(
                          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                          isActive
                            ? "bg-accent text-accent-foreground"
                            : "text-foreground hover:bg-accent"
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
        </nav>
      </SheetContent>
    </Sheet>
  )
}
