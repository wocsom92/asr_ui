import axios from "axios"

const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
})

const AUTH_PATHS = ["/auth/me", "/auth/login", "/auth/register", "/auth/refresh", "/auth/logout"]
let refreshPromise: Promise<void> | null = null

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const requestPath = original?.url ?? ""

    if (AUTH_PATHS.some((p) => requestPath.includes(p))) {
      return Promise.reject(error)
    }

    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      try {
        if (!refreshPromise) {
          refreshPromise = axios
            .post("/api/v1/auth/refresh", {}, { withCredentials: true })
            .then(() => {})
            .finally(() => {
              refreshPromise = null
            })
        }
        await refreshPromise
        return api(original)
      } catch {
        return Promise.reject(error)
      }
    }
    return Promise.reject(error)
  }
)

export default api
