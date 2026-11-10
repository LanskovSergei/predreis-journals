import { inBusinessTz } from './time'
import type { Phase, RecordSource, RecordStatus, Result, Role } from '../types/api.types'

export const roleLabels: Record<Role, string> = {
  client: 'Клиент',
  dispatcher: 'Диспетчер',
  medic: 'Медик',
  mechanic: 'Механик',
  predreis: 'Предрейс',
  admin: 'Админ',
  superadmin: 'Суперадмин',
}

export const phaseLabels: Record<Phase, string> = { pre: 'Предрейсовый', post: 'Послерейсовый' }

export const resultLabels: Record<Result, string> = { admitted: 'Допущен', not_admitted: 'Не допущен' }

export const statusLabels: Record<RecordStatus, string> = {
  unsigned: 'Не подписана',
  signed: 'Подписана',
  in_journal: 'В журнале',
}

export const sourceLabels: Record<RecordSource, string> = { epl: 'ЭПЛ', manual: 'Бумага', ocr: 'Скан' }

/** Дата и время по Москве (журналы ведутся по московскому времени). */
export const formatDateTime = (iso?: string | null): string =>
  iso ? inBusinessTz(iso).format('DD.MM.YYYY HH:mm') : '—'

export const formatDate = (iso?: string | null): string => (iso ? inBusinessTz(iso).format('DD.MM.YYYY') : '—')

/** Скачивание файла из Blob. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
