/**
 * Сессия общая с платформой: фронтенд Предрейса хранит токены в localStorage под этими ключами,
 * журналы на том же домене читают их и обновляют тем же методом /api/v1/auth/refresh.
 */
const ACCESS_TOKEN_KEY = 'predreis_access_token'
const REFRESH_TOKEN_KEY = 'predreis_refresh_token'
const USER_KEY = 'predreis_user'

export interface PlatformUser {
  firstName?: string
  lastName?: string
  middleName?: string
  email?: string
  role?: string
}

export const DEV_LOGIN = import.meta.env.VITE_DEV_LOGIN === '1'

export const session = {
  accessToken: (): string | null => localStorage.getItem(ACCESS_TOKEN_KEY),
  refreshToken: (): string | null => localStorage.getItem(REFRESH_TOKEN_KEY),
  setTokens(access: string, refresh?: string | null): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, access)
    if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
  },
  clear(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
  /** Профиль, который сохранила платформа (ФИО и почта для шапки до ответа /me). */
  platformUser(): PlatformUser | null {
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? (JSON.parse(raw) as PlatformUser) : null
    } catch {
      return null
    }
  },
}

/** Куда отправить человека без сессии: в бою — на вход платформы, на стенде — на вход журналов. */
export function goToLogin(): void {
  window.location.assign(DEV_LOGIN ? '/journals/login' : '/login')
}

/** Возврат в кабинет платформы (полный переход: это другое приложение на том же домене). */
export function goToPlatform(path = '/dashboard'): void {
  window.location.assign(path)
}
