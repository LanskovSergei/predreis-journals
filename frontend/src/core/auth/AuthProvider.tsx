import { createContext, useCallback, useEffect, useState, type ReactNode } from 'react'
import { JournalsService } from '../api/journals.service'
import type { Kind, Me } from '../../shared/types/api.types'
import { TokenService } from './token.service'

export interface AuthContextValue {
  user: Me | null
  isLoading: boolean
  authError: string | null
  hasPermission: (permission: string) => boolean
  hasJournalAccess: (kind: Kind) => boolean
  refreshProfile: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [authError, setAuthError] = useState<string | null>(null)

  const refreshProfile = useCallback(async () => {
    if (!TokenService.getAccessToken()) {
      setIsLoading(false)
      if (!(TokenService.isDevLogin && window.location.pathname.startsWith('/journals/login'))) {
        TokenService.redirectToLogin()
      }
      return
    }

    setIsLoading(true)
    try {
      const profile = await JournalsService.getMe()
      setUser(profile)
      setAuthError(null)
    } catch (err) {
      const status = (err as { response?: { data?: { error?: { message?: string } } } })?.response
      setAuthError(status?.data?.error?.message ?? 'Не удалось загрузить профиль')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshProfile()
  }, [refreshProfile])

  const hasPermission = useCallback(
    (permission: string) => Boolean(user?.permissions.includes(permission)),
    [user]
  )

  const hasJournalAccess = useCallback(
    (kind: Kind) => Boolean(user?.journals.includes(kind)),
    [user]
  )

  const value: AuthContextValue = {
    user,
    isLoading,
    authError,
    hasPermission,
    hasJournalAccess,
    refreshProfile,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
