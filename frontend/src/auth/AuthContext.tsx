import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchMe } from '@/api/journals'
import type { Kind, Me } from '@/api/types'
import { DEV_LOGIN, goToLogin, session } from './session'

interface AuthState {
  me: Me | null
  loading: boolean
  /** Ошибка загрузки профиля, кроме «не вошёл» (тогда уходим на вход) */
  error: string | null
  can: (permission: string) => boolean
  hasJournal: (kind: Kind) => boolean
  reload: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    if (!session.accessToken()) {
      setLoading(false)
      if (!(DEV_LOGIN && window.location.pathname.startsWith('/journals/login'))) goToLogin()
      return
    }
    setLoading(true)
    try {
      setMe(await fetchMe())
      setError(null)
    } catch (err) {
      const status = (err as { response?: { status?: number; data?: { error?: { message?: string } } } })
        ?.response
      // 401 обрабатывает клиент API (обновление токена или вход); 403 — нет доступа к журналам
      setError(status?.data?.error?.message ?? 'Не удалось загрузить профиль')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const can = useCallback((permission: string) => Boolean(me?.permissions.includes(permission)), [me])
  const hasJournal = useCallback((kind: Kind) => Boolean(me?.journals.includes(kind)), [me])

  return (
    <AuthContext.Provider value={{ me, loading, error, can, hasJournal, reload }}>{children}</AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth вне AuthProvider')
  return ctx
}
