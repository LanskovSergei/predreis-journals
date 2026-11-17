import { useEffect, useRef, useState } from 'react'
import { JournalsService } from '../../../core/api/journals.service'
import type { AnyRecord, Kind, MedicalRecord } from '../../../shared/types/api.types'
import type { RecordsFilters } from '../types'

/** С какой длины строки ищем: столько же требует сервер (min_length=3). */
export const MIN_SEARCH_LENGTH = 3
const DEBOUNCE_MS = 300
const SAMPLE_SIZE = 50
const MAX_SUGGESTIONS = 8

export interface SearchSuggestion {
  /** Что подставится в поиск и уйдёт на сервер. */
  value: string
  /** Что видит пользователь в списке. */
  label: string
}

/** Подсказка из записи: ФИО водителя для медосмотра, ТС и госномер для техконтроля. */
function toSuggestion(kind: Kind, record: AnyRecord): SearchSuggestion | null {
  if (kind === 'medical') {
    const name = (record as MedicalRecord).driver_full_name ?? record.snapshot?.driver?.full_name
    return name ? { value: name, label: name } : null
  }
  const vehicle = record.snapshot?.vehicle
  if (!vehicle?.plate) return null
  const title = [vehicle.brand, vehicle.model].filter(Boolean).join(' ')
  // Ищем по госномеру: он однозначен и точно найдётся подстрокой на сервере.
  return { value: vehicle.plate, label: title ? `${title}, ${vehicle.plate}` : vehicle.plate }
}

/**
 * Подсказки для поиска в архиве по мере ввода.
 *
 * Берутся из записей, которые сервер находит по введённой строке с учётом уже выбранных
 * организации и периода, поэтому работают для всех ролей, включая клиента без доступа к каталогу.
 */
export function useSearchSuggestions(
  kind: Kind,
  searchParam: string,
  text: string,
  filters: Pick<RecordsFilters, 'organizationId' | 'range'>,
) {
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const requestId = useRef(0)

  const query = text.trim()
  const orgId = filters.organizationId
  const from = filters.range?.[0]?.format('YYYY-MM-DD')
  const to = filters.range?.[1]?.format('YYYY-MM-DD')

  useEffect(() => {
    if (query.length < MIN_SEARCH_LENGTH) {
      setSuggestions([])
      setLoading(false)
      return
    }
    const current = ++requestId.current
    setLoading(true)
    const timer = window.setTimeout(async () => {
      const params: Record<string, unknown> = { page: 1, page_size: SAMPLE_SIZE, [searchParam]: query }
      if (orgId) params.organization_id = orgId
      if (from) params.date_from = from
      if (to) params.date_to = to
      try {
        const page = await JournalsService.getRecords(kind, params)
        if (current !== requestId.current) return // пришёл ответ на устаревший ввод
        const seen = new Map<string, SearchSuggestion>()
        for (const record of page.items) {
          const s = toSuggestion(kind, record)
          if (s && !seen.has(s.value)) seen.set(s.value, s)
          if (seen.size >= MAX_SUGGESTIONS) break
        }
        setSuggestions([...seen.values()])
      } catch {
        if (current === requestId.current) setSuggestions([])
      } finally {
        if (current === requestId.current) setLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [kind, searchParam, query, orgId, from, to])

  return { suggestions, loading }
}
