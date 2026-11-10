import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Space, Typography } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { AnyRecord, Kind, Page } from '../../../shared/types/api.types'
import type { RecordsFilters } from '../types'

export const PAGE_SIZE = 10

export const isSigning = (r: AnyRecord) => r.signing_status === 'queued' || r.signing_status === 'pending'

export function useRecordsQuery(kind: Kind, filters: RecordsFilters, page: number, searchParam: string) {
  const { message, notification } = App.useApp()
  const [data, setData] = useState<Page<AnyRecord> | null>(null)
  const [loading, setLoading] = useState(true)
  const [trackedSigning, setTrackedSigning] = useState<Record<string, boolean>>({})

  const queryParams = useMemo(() => {
    const q: Record<string, unknown> = { page, page_size: PAGE_SIZE }
    if (filters.organizationId) q.organization_id = filters.organizationId
    if (filters.range?.[0]) q.date_from = filters.range[0].format('YYYY-MM-DD')
    if (filters.range?.[1]) q.date_to = filters.range[1].format('YYYY-MM-DD')
    if (filters.text) q[searchParam] = filters.text
    if (filters.result) q.result = filters.result
    if (filters.signed) q.is_signed = filters.signed === '1'
    if (filters.note) q.has_note = filters.note === '1'
    return q
  }, [filters, page, searchParam])

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true)
      try {
        setData(await JournalsService.getRecords(kind, queryParams))
      } catch (err) {
        if (!quiet) message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить записи'))
      } finally {
        if (!quiet) setLoading(false)
      }
    },
    [kind, queryParams, message]
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!data?.items.some(isSigning)) return
    const timer = window.setInterval(() => void load(true), 5000)
    return () => window.clearInterval(timer)
  }, [data, load])

  useEffect(() => {
    if (!data) return

    const newlyFinished: AnyRecord[] = []
    const newTracked = { ...trackedSigning }
    let changed = false

    data.items.forEach((r) => {
      if (isSigning(r)) {
        if (!newTracked[r.id]) {
          newTracked[r.id] = true
          changed = true
        }
      } else if (newTracked[r.id]) {
        newlyFinished.push(r)
        delete newTracked[r.id]
        changed = true
      }
    })

    if (newlyFinished.length > 0) {
      const success = newlyFinished.filter((r) => r.status === 'signed')
      const failed = newlyFinished.filter((r) => r.signing_status === 'failed')

      if (success.length > 0 && failed.length === 0) {
        notification.success({
          message: 'Подписание завершено',
          description: `Успешно подписано записей: ${success.length}`,
          placement: 'bottomRight',
        })
      } else if (failed.length > 0) {
        notification.error({
          message: 'Результат подписания',
          description: (
            <Space direction="vertical" size={2}>
              {success.length > 0 && <Typography.Text>Успешно: {success.length}</Typography.Text>}
              <Typography.Text type="danger">С ошибкой: {failed.length}</Typography.Text>
              <ul style={{ paddingLeft: 16, margin: '4px 0' }}>
                {[...new Set(failed.map((r) => r.signing_error || 'Неизвестная ошибка'))].map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </Space>
          ),
          duration: 0,
          placement: 'bottomRight',
        })
      }
    }

    if (changed) {
      setTrackedSigning(newTracked)
    }
  }, [data, notification, trackedSigning])

  return { data, loading, load, setTrackedSigning }
}
