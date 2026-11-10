import type { AxiosError } from 'axios'

interface ApiErrorResponse {
  error?: {
    code?: string
    message?: string
  }
}

export class ApiErrorUtils {
  static getMessage(err: unknown, fallback = 'Не удалось выполнить действие'): string {
    const axiosError = err as AxiosError<ApiErrorResponse>
    const data = axiosError?.response?.data

    if (data?.error?.message) {
      return data.error.message
    }

    if (axiosError?.code === 'ECONNABORTED') {
      return 'Сервер не ответил вовремя, попробуйте ещё раз'
    }

    if (axiosError?.response === undefined && axiosError?.isAxiosError) {
      return 'Нет связи с сервером журналов'
    }

    return fallback
  }

  static getCode(err: unknown): string | undefined {
    const axiosError = err as AxiosError<ApiErrorResponse>
    return axiosError?.response?.data?.error?.code
  }
}
