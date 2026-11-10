import { useState } from 'react'
import { App, Space, Typography, Input } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { AnyRecord, Kind, RecordAction } from '../../../shared/types/api.types'
import { formatDateTime, saveBlob } from '../../../shared/utils/labels'
import { getDriverName, getVehicleLabel } from '../utils/recordLabels'

export function useRecordActions(
  kind: Kind,
  load: (quiet?: boolean) => Promise<void>,
  setTrackedSigning: React.Dispatch<React.SetStateAction<Record<string, boolean>>>,
  setSelected: (keys: string[]) => void,
  setEditing: (record: AnyRecord | null) => void,
  setFormOpen: (open: boolean) => void
) {
  const { message, modal } = App.useApp()
  const [busy, setBusy] = useState(false)

  const reportBatch = (title: string, okCount: number, results: { ok: boolean; message?: string | null }[]) => {
    const failed = results.filter((r) => !r.ok)
    if (failed.length === 0) {
      message.success(`${title}: ${okCount}`)
      return
    }
    modal.warning({
      title: `${title}: ${okCount}, не получилось: ${failed.length}`,
      content: (
        <ul style={{ paddingLeft: 18, margin: 0 }}>
          {[...new Set(failed.map((r) => r.message ?? 'Причина не указана'))].map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ),
    })
  }

  const sign = async (ids: string[]) => {
    setBusy(true)
    try {
      const res = await JournalsService.signRecordsBatch(kind, ids)
      reportBatch('Отправлено на подпись', res.signed, res.results)

      const queuedIds = res.results.filter((r) => r.ok).map((r) => r.record_id)
      if (queuedIds.length > 0) {
        setTrackedSigning((prev) => {
          const next = { ...prev }
          queuedIds.forEach((id) => {
            next[id] = true
          })
          return next
        })
      }

      setSelected([])
      await load(true)
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось отправить на подпись'))
    } finally {
      setBusy(false)
    }
  }

  const removeSelected = (selected: string[]) =>
    modal.confirm({
      title: `Удалить выбранные записи (${selected.length})?`,
      content: 'Удаляются только неподписанные записи. Действие нельзя отменить.',
      okText: 'Удалить',
      okButtonProps: { danger: true },
      cancelText: 'Отмена',
      onOk: async () => {
        try {
          const res = await JournalsService.deleteRecordsBatch(kind, selected)
          reportBatch('Удалено', res.deleted, res.results)
          setSelected([])
          await load(true)
        } catch (err) {
          message.error(ApiErrorUtils.getMessage(err, 'Не удалось удалить записи'))
        }
      },
    })

  const download = async (body: Record<string, unknown>) => {
    setBusy(true)
    try {
      const { blob, filename } = await JournalsService.exportPdf(kind, body)
      saveBlob(blob, filename)
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось сформировать выгрузку'))
    } finally {
      setBusy(false)
    }
  }

  const runAction = (action: RecordAction, record: AnyRecord) => {
    if (action === 'sign') void sign([record.id])
    if (action === 'edit') {
      setEditing(record)
      setFormOpen(true)
    }
    if (action === 'clear_note') {
      modal.confirm({
        title: 'Снять примечание?',
        content: record.note,
        okText: 'Снять',
        cancelText: 'Отмена',
        onOk: async () => {
          try {
            await JournalsService.clearRecordNote(kind, record.id)
            message.success('Примечание снято')
            await load(true)
          } catch (err) {
            message.error(ApiErrorUtils.getMessage(err))
          }
        },
      })
    }
    if (action === 'delete') {
      modal.confirm({
        title: 'Удалить запись?',
        content: `${formatDateTime(record.performed_at)}, ${kind === 'medical' ? getDriverName(record) : getVehicleLabel(record)}`,
        okText: 'Удалить',
        okButtonProps: { danger: true },
        cancelText: 'Отмена',
        onOk: async () => {
          try {
            await JournalsService.deleteRecord(kind, record.id)
            message.success('Запись удалена')
            await load(true)
          } catch (err) {
            message.error(ApiErrorUtils.getMessage(err))
          }
        },
      })
    }
    if (action === 'request_deletion') {
      let reason = ''
      modal.confirm({
        title: 'Запросить удаление подписанной записи',
        content: (
          <Space orientation="vertical" style={{ width: '100%' }}>
            <Typography.Text type="secondary">
              Удаление подписанной записи подтверждает Админ или Суперадмин.
            </Typography.Text>
            <Input.TextArea rows={3} placeholder="Причина удаления" onChange={(e) => (reason = e.target.value)} />
          </Space>
        ),
        okText: 'Отправить запрос',
        cancelText: 'Отмена',
        onOk: async () => {
          try {
            await JournalsService.requestRecordDeletion(kind, record.id, reason.trim())
            message.success('Запрос на удаление отправлен')
            await load(true)
          } catch (err) {
            message.error(ApiErrorUtils.getMessage(err))
          }
        },
      })
    }
  }

  return { busy, sign, removeSelected, download, runAction }
}
