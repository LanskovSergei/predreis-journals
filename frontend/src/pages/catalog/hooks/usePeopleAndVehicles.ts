import { useCallback, useEffect, useState } from 'react'
import { App } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { DriverFull, Page, VehicleFull } from '../../../shared/types/api.types'

export function usePeopleAndVehicles(kind: 'drivers' | 'vehicles') {
  const { message } = App.useApp()
  const [orgId, setOrgId] = useState<string | undefined>()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<DriverFull | VehicleFull> | null>(null)
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<DriverFull | 'new' | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!orgId) {
      setData(null)
      return
    }
    setLoading(true)
    try {
      const params = { organization_id: orgId, q: q || undefined, page, page_size: 10 }
      setData(
        kind === 'drivers'
          ? await JournalsService.getDriversPage(params)
          : await JournalsService.getVehiclesPage(params),
      )
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить список'))
    } finally {
      setLoading(false)
    }
  }, [orgId, q, page, kind, message])

  useEffect(() => {
    void load()
  }, [load])

  const save = async (values: Record<string, unknown>) => {
    setSaving(true)
    try {
      if (kind === 'drivers') {
        const birth =
          values.birth_date && typeof values.birth_date === 'object' && 'format' in values.birth_date
            ? (values.birth_date as { format: (f: string) => string }).format('YYYY-MM-DD')
            : (values.birth_date as string | null | undefined) ?? null
        const body: Record<string, unknown> = { ...values, organization_id: orgId, birth_date: birth }
        if (editing && editing !== 'new') {
          await JournalsService.updateDriver(editing.id, {
            gender: body.gender ?? null,
            snils: body.snils ?? null,
            ...(editing.origin === 'manual' ? { full_name: body.full_name, birth_date: body.birth_date } : {}),
          })
        } else {
          await JournalsService.createDriver(body)
        }
      } else {
        await JournalsService.createVehicle({ ...values, organization_id: orgId })
      }
      message.success(
        editing && editing !== 'new'
          ? 'Изменения сохранены'
          : kind === 'drivers'
            ? 'Водитель добавлен'
            : 'ТС добавлено',
      )
      setEditing(null)
      await load()
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось сохранить'))
    } finally {
      setSaving(false)
    }
  }

  return {
    orgId, setOrgId,
    q, setQ,
    page, setPage,
    data, loading,
    editing, setEditing,
    saving, save,
  }
}
