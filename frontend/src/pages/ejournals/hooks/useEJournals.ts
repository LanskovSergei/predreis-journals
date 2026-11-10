import { useCallback, useEffect, useState } from 'react'
import { App } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { EJournal, EJournalStatus, Kind } from '../../../shared/types/api.types'
import { saveBlob } from '../../../shared/utils/labels'

export function useEJournals() {
  const { message } = App.useApp()
  const [items, setItems] = useState<EJournal[]>([])
  const [loading, setLoading] = useState(true)
  const [kind, setKind] = useState<Kind | undefined>()
  const [status, setStatus] = useState<EJournalStatus | undefined>()
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true)
      try {
        setItems(await JournalsService.getEJournals({ kind, status_filter: status }))
      } catch (err) {
        if (!quiet) message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить журналы'))
      } finally {
        if (!quiet) setLoading(false)
      }
    },
    [kind, status, message]
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!items.some((j) => j.status === 'signing')) return
    const timer = window.setInterval(() => void load(true), 5000)
    return () => window.clearInterval(timer)
  }, [items, load])

  const runAction = async (action: () => Promise<unknown>, done: string) => {
    try {
      await action()
      message.success(done)
      await load(true)
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err))
    }
  }

  const openFile = async (j: EJournal, what: 'preview' | 'download') => {
    try {
      const { blob, filename } = await JournalsService.getEJournalFile(j.id, what)
      if (what === 'preview') window.open(URL.createObjectURL(blob), '_blank', 'noopener')
      else saveBlob(blob, filename)
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось получить файл журнала'))
    }
  }

  const create = async (values: any) => {
    const [from, to] = values.period
    setCreating(true)
    try {
      const journal = await JournalsService.createEJournal({
        kind: values.kind,
        organization_id: values.organization_id,
        period_from: from.format('YYYY-MM-DD'),
        period_to: to.format('YYYY-MM-DD'),
      })
      message.success(`Черновик журнала сформирован: записей ${journal.record_count}`)
      setCreateOpen(false)
      await load(true)
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось сформировать журнал'))
    } finally {
      setCreating(false)
    }
  }

  return {
    items, loading,
    kind, setKind,
    status, setStatus,
    createOpen, setCreateOpen,
    creating, create,
    runAction, openFile
  }
}
