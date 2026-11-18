import { useState } from 'react'
import { App, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { JournalsService } from '../../core/api/journals.service'
import { ApiErrorUtils } from '../utils/error.utils'
import { PersonVehicleFormModal } from './PersonVehicleFormModal'

interface Props {
  kind: 'drivers' | 'vehicles'
  organizationId?: string
  /** Новая карточка создана — id, чтобы сразу подставить её в форму. */
  onCreated: (id: string) => void
}

/** Дата из DatePicker (dayjs) или строка → YYYY-MM-DD для API. */
function toIsoDate(value: unknown): string | null {
  if (value && typeof value === 'object' && 'format' in value) {
    return (value as { format: (f: string) => string }).format('YYYY-MM-DD')
  }
  return (value as string | null | undefined) ?? null
}

/**
 * Ссылка «+ Новый водитель» / «+ Новое ТС» под полем выбора в форме записи.
 *
 * Для медика и механика: раздела «Картотека» у них нет, а водителя или ТС, которого ещё
 * нет в списке, нужно добавить, не уходя из записи. Новая карточка сразу подставляется в форму.
 */
export function QuickAddCatalogItem({ kind, organizationId, onCreated }: Props) {
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const save = async (values: Record<string, unknown>) => {
    if (!organizationId) return
    setSaving(true)
    try {
      const created =
        kind === 'drivers'
          ? await JournalsService.createDriver({
              ...values,
              organization_id: organizationId,
              birth_date: toIsoDate(values.birth_date),
            })
          : await JournalsService.createVehicle({ ...values, organization_id: organizationId })
      const id = Array.isArray(created) ? created[0]?.id : undefined
      message.success(kind === 'drivers' ? 'Водитель добавлен' : 'ТС добавлено')
      setOpen(false)
      if (id) onCreated(String(id))
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось добавить'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Button
        type="link"
        size="small"
        icon={<PlusOutlined />}
        disabled={!organizationId}
        onClick={() => setOpen(true)}
        style={{ paddingInline: 0 }}
      >
        {kind === 'drivers' ? 'Новый водитель' : 'Новое ТС'}
      </Button>
      <PersonVehicleFormModal
        kind={kind}
        editing={open ? 'new' : null}
        saving={saving}
        onClose={() => setOpen(false)}
        onSave={save}
      />
    </>
  )
}
