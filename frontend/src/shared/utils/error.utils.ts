import type { AxiosError } from 'axios'

interface ApiErrorResponse {
  error?: {
    code?: string
    message?: string
  }
}

export class ApiErrorUtils {
  static getMessage(err: unknown, fallback = 'Не удалось выполнить действие'): string {
    const axiosError = err as AxiosError<ApiErrorResponse | Blob>
    const data = axiosError?.response?.data

    if (data && typeof data === 'object' && !(data instanceof Blob) && data.error?.message) {
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

  /** Для выгрузок (responseType: blob) тело ошибки — Blob с JSON. */
  static async getMessageAsync(err: unknown, fallback = 'Не удалось выполнить действие'): Promise<string> {
    const data = (err as AxiosError<unknown>)?.response?.data
    if (typeof Blob !== 'undefined' && data instanceof Blob) {
      try {
        const parsed = JSON.parse(await data.text()) as ApiErrorResponse
        if (parsed?.error?.message) return parsed.error.message
      } catch {
        /* не JSON */
      }
    }
    return ApiErrorUtils.getMessage(err, fallback)
  }

  static getCode(err: unknown): string | undefined {
    const axiosError = err as AxiosError<ApiErrorResponse>
    return axiosError?.response?.data?.error?.code
  }
}
