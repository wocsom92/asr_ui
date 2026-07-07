import { create } from "zustand"

export type Theme = "light" | "dark"

const STORAGE_KEY = "asr-ui-theme"

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "light"
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === "light" || stored === "dark") return stored
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return
  document.documentElement.classList.toggle("dark", theme === "dark")
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: getInitialTheme(),
  setTheme: (theme) => {
    applyTheme(theme)
    window.localStorage.setItem(STORAGE_KEY, theme)
    set({ theme })
  },
  toggleTheme: () => {
    get().setTheme(get().theme === "dark" ? "light" : "dark")
  },
}))

// Apply the persisted/system theme on module load so there is no flash.
applyTheme(getInitialTheme())
