import { useCallback, useEffect, useState } from 'react'
import { App } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { AnyRecord, DeletionRequest, DeletionStatus } from '../../../shared/types/api.types'

export function useDeletionRequests() {
  const { message, modal } = App.useApp()
  const [status, setStatus] = useState<DeletionStatus>('pending')
  const [items, setItems] = useState<DeletionRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [viewing, setViewing] = useState<{ request: DeletionRequest; record: AnyRecord | null } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await JournalsService.getDeletionRequests(status))
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить запросы'))
    } finally {
      setLoading(false)
    }
  }, [status, message])

  useEffect(() => {
    void load()
  }, [load])

  const openRecord = async (request: DeletionRequest) => {
    setViewing({ request, record: null })
    try {
      setViewing({ request, record: await JournalsService.getRecord(request.record_kind, request.record_id) })
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось открыть запись'))
    }
  }

  const decide = (request: DeletionRequest, decision: 'approve' | 'reject', comment: string) => {
    return async () => {
      try {
        await JournalsService.resolveDeletionRequest(request.id, decision, comment.trim())
        message.success(decision === 'approve' ? 'Запись удалена' : 'Запрос отклонён')
        setViewing(null)
        await load()
      } catch (err) {
        message.error(ApiErrorUtils.getMessage(err))
      }
    }
  }

  return {
    status, setStatus,
    items, loading,
    viewing, setViewing,
    openRecord, decide
  }
}
