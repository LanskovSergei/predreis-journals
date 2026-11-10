export interface PlatformUser {
  firstName?: string
  lastName?: string
  middleName?: string
  email?: string
  role?: string
}

export class TokenService {
  private static readonly ACCESS_KEY = 'predreis_access_token'
  private static readonly REFRESH_KEY = 'predreis_refresh_token'
  private static readonly USER_KEY = 'predreis_user'

  static get isDevLogin(): boolean {
    return import.meta.env.VITE_DEV_LOGIN === '1'
  }

  static getAccessToken(): string | null {
    return localStorage.getItem(this.ACCESS_KEY)
  }

  static getRefreshToken(): string | null {
    return localStorage.getItem(this.REFRESH_KEY)
  }

  static setTokens(access: string, refresh?: string | null): void {
    localStorage.setItem(this.ACCESS_KEY, access)
    if (refresh) {
      localStorage.setItem(this.REFRESH_KEY, refresh)
    }
  }

  static clear(): void {
    localStorage.removeItem(this.ACCESS_KEY)
    localStorage.removeItem(this.REFRESH_KEY)
    localStorage.removeItem(this.USER_KEY)
  }

  static getPlatformUser(): PlatformUser | null {
    try {
      const raw = localStorage.getItem(this.USER_KEY)
      return raw ? (JSON.parse(raw) as PlatformUser) : null
    } catch {
      return null
    }
  }

  static redirectToLogin(): void {
    window.location.assign(this.isDevLogin ? '/journals/login' : '/login')
  }

  static redirectToPlatform(path = '/dashboard'): void {
    window.location.assign(path)
  }
}
