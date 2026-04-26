import { create } from "zustand"
import type { User } from "@/types"
import api from "@/api/client"

interface AuthState {
  user: User | null
  loading: boolean
  setUser: (user: User | null) => void
  fetchUser: () => Promise<void>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,
  setUser: (user) => set({ user }),
  fetchUser: async () => {
    try {
      const { data } = await api.get("/auth/me")
      set({ user: data, loading: false })
    } catch {
      set({ user: null, loading: false })
    }
  },
  logout: async () => {
    await api.post("/auth/logout")
    set({ user: null })
  },
}))
