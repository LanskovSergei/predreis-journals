import { useEffect, useState } from 'react'
import { App } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { SpecialistsList } from '../../../shared/types/api.types'

export function useSpecialists() {
  const { message } = App.useApp()
  const [role, setRole] = useState<'medic' | 'mechanic'>('medic')
  const [data, setData] = useState<SpecialistsList | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    
    JournalsService.getSpecialistsList(role)
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((err) => {
        if (!cancelled) message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить специалистов'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
      
    return () => {
      cancelled = true
    }
  }, [role, message])

  return {
    role, setRole,
    data, loading
  }
}
