import { useCallback, useEffect, useState } from 'react'
import { App } from 'antd'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { OrganizationFull, Page } from '../../../shared/types/api.types'

export function useOrganizations() {
  const { message } = App.useApp()
  const [q, setQ] = useState('')
  const [origin, setOrigin] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<OrganizationFull> | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<OrganizationFull | 'new' | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await JournalsService.getOrganizationsPage({ q: q || undefined, origin, page, page_size: 10, only_active: false }))
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось загрузить организации'))
    } finally {
      setLoading(false)
    }
  }, [q, origin, page, message])

  useEffect(() => {
    void load()
  }, [load])

  const save = async (values: any) => {
    const body = {
      ...values,
      contract_date: values.contract_date ? values.contract_date.format('YYYY-MM-DD') : null,
      contract_until: values.contract_until ? values.contract_until.format('YYYY-MM-DD') : null,
    }
    setSaving(true)
    try {
      if (editing === 'new') {
        await JournalsService.createOrganization(body)
      } else if (editing?.origin === 'platform') {
        await JournalsService.updateOrganization(editing.id, { contract_type: values.contract_type ?? null, note: values.note ?? null })
      } else if (editing) {
        await JournalsService.updateOrganization(editing.id, body)
      }
      message.success(editing === 'new' ? 'Организация добавлена' : 'Изменения сохранены')
      setEditing(null)
      await load()
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось сохранить организацию'))
    } finally {
      setSaving(false)
    }
  }

  return {
    q, setQ,
    origin, setOrigin,
    page, setPage,
    data, loading,
    editing, setEditing,
    saving, save
  }
}
