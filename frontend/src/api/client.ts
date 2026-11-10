import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { DEV_LOGIN, goToLogin, session } from '@/auth/session'

/** API журналов: на домене платформы — /journals/api/v1 (nginx срезает /journals). */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? '/journals',
  headers: { Accept: 'application/json' },
  timeout: 60000,
})

api.interceptors.request.use((config) => {
  const token = session.accessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing: Promise<string | null> | null = null

/** Обновляет токен тем же методом, что и платформа; на стенде (вход журналов) обновления нет. */
async function refreshToken(): Promise<string | null> {
  const refresh = session.refreshToken()
  if (DEV_LOGIN || !refresh) return null
  try {
    const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: refresh })
    session.setTokens(data.access_token, data.refresh_token ?? refresh)
    return data.access_token as string
  } catch {
    return null
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true
      refreshing ??= refreshToken().finally(() => {
        refreshing = null
      })
      const token = await refreshing
      if (token) {
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      }
      session.clear()
      goToLogin()
    }
    return Promise.reject(error)
  },
)

/** Текст ошибки API журналов ({ error: { code, message } }) для показа человеку. */
export function errorMessage(err: unknown, fallback = 'Не удалось выполнить действие'): string {
  const data = (err as AxiosError<{ error?: { message?: string } }>)?.response?.data
  if (data?.error?.message) return data.error.message
  if ((err as AxiosError)?.code === 'ECONNABORTED') return 'Сервер не ответил вовремя, попробуйте ещё раз'
  if ((err as AxiosError)?.response === undefined && (err as AxiosError)?.isAxiosError) {
    return 'Нет связи с сервером журналов'
  }
  return fallback
}

export function errorCode(err: unknown): string | undefined {
  return (err as AxiosError<{ error?: { code?: string } }>)?.response?.data?.error?.code
}
