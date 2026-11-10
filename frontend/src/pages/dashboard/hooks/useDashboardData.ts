import { useEffect, useState } from 'react'
import { App } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { MyCertificates, Stats } from '../../../shared/types/api.types'

export function useDashboardData(isSpecialist: boolean) {
  const { message } = App.useApp()
  const [stats, setStats] = useState<Stats | null>(null)
  const [cert, setCert] = useState<MyCertificates | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    
    const loadData = async () => {
      try {
        const [s, c] = await Promise.all([
          JournalsService.getStats(),
          isSpecialist ? JournalsService.getMyCertificates().catch(() => null) : Promise.resolve(null),
        ])
        
        if (!cancelled) {
          setStats(s)
          setCert(c)
        }
      } catch (err) {
        if (!cancelled) {
          message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить сводку'))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }
    
    void loadData()
    
    return () => {
      cancelled = true
    }
  }, [isSpecialist, message])

  return { stats, cert, loading }
}
