import { useEffect, useState } from 'react'
import { JournalsService } from '../../core/api/journals.service'

/** Названия организаций по идентификатору (для таблиц, где API отдаёт только id). */
export function useOrganizationNames(): Record<string, string> {
  const [names, setNames] = useState<Record<string, string>>({})
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      const result: Record<string, string> = {}
      for (let page = 1; page <= 20; page += 1) {
        const data = await JournalsService.getOrganizationsPage({ page, page_size: 100 })
        for (const o of data.items) result[o.id] = o.short_name || o.name
        if (data.items.length < 100) break
      }
      if (!cancelled) setNames(result)
    }
    load().catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])
  return names
}
