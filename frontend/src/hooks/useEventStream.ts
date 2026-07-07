import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useAuthStore } from "@/stores/auth"

/**
 * Subscribes to the backend SSE stream and invalidates the affected TanStack queries
 * when the server pushes a state change, replacing most polling. The browser's
 * EventSource reconnects automatically on transient errors.
 */
export function useEventStream() {
  const qc = useQueryClient()
  const userId = useAuthStore((s) => s.user?.id)

  useEffect(() => {
    if (!userId) return

    const source = new EventSource("/api/v1/events")

    const invalidateJobViews = () => {
      void qc.invalidateQueries({ queryKey: ["transcriptions"] })
      void qc.invalidateQueries({ queryKey: ["files"] })
    }

    const handleMessage = (event: MessageEvent) => {
      let payload: { type?: string } = {}
      try {
        payload = JSON.parse(event.data)
      } catch {
        payload = {}
      }
      if (payload.type === "worker.updated") {
        void qc.invalidateQueries({ queryKey: ["workers"] })
        return
      }
      // job.updated / summary.updated
      invalidateJobViews()
      void qc.invalidateQueries({ queryKey: ["workers"] })
    }

    source.addEventListener("message", handleMessage)
    source.addEventListener("ready", invalidateJobViews)

    return () => {
      source.removeEventListener("message", handleMessage)
      source.removeEventListener("ready", invalidateJobViews)
      source.close()
    }
  }, [qc, userId])
}
