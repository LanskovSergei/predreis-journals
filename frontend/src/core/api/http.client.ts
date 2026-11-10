import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { TokenService } from '../auth/token.service'

export const httpClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? '/journals',
  headers: { Accept: 'application/json' },
  timeout: 60000,
})

httpClient.interceptors.request.use((config) => {
  const token = TokenService.getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshingPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = TokenService.getRefreshToken()
  if (TokenService.isDevLogin || !refresh) return null

  try {
    const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: refresh })
    TokenService.setTokens(data.access_token, data.refresh_token ?? refresh)
    return data.access_token as string
  } catch {
    return null
  }
}

httpClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true

      refreshingPromise ??= refreshAccessToken().finally(() => {
        refreshingPromise = null
      })

      const newToken = await refreshingPromise

      if (newToken) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return httpClient(originalRequest)
      }

      TokenService.clear()
      TokenService.redirectToLogin()
    }

    return Promise.reject(error)
  }
)
