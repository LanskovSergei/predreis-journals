import { useEffect } from 'react'
import { Modal, Form, Input, DatePicker, Radio, Typography } from 'antd'
import dayjs from 'dayjs'
import type { DriverFull } from '../../../shared/types/api.types'

interface Props {
  kind: 'drivers' | 'vehicles'
  editing: DriverFull | 'new' | null
  saving: boolean
  onClose: () => void
  onSave: (values: Record<string, unknown>) => Promise<void>
}

export function PersonVehicleFormModal({ kind, editing, saving, onClose, onSave }: Props) {
  const [form] = Form.useForm()
  const isEdit = editing !== null && editing !== 'new'
  const isPlatform = isEdit && editing.origin === 'platform'

  useEffect(() => {
    if (!editing) return
    form.resetFields()
    if (editing !== 'new' && kind === 'drivers') {
      form.setFieldsValue({
        ...editing,
        birth_date: editing.birth_date ? dayjs(editing.birth_date) : undefined,
      })
    }
  }, [editing, form, kind])

  const handleOk = () => {
    form.validateFields().then(onSave).catch(() => {})
  }

  return (
    <Modal
      title={kind === 'drivers' ? (isEdit ? 'Водитель' : 'Новый водитель') : 'Новое ТС'}
      open={editing !== null}
      onCancel={onClose}
      onOk={handleOk}
      okText={isEdit ? 'Сохранить' : 'Добавить'}
      cancelText="Отмена"
      confirmLoading={saving}
      destroyOnHidden
    >
      {isPlatform && (
        <Typography.Paragraph type="secondary">
          ФИО и дату рождения водителя с платформы ведёт ПРЕДРЕЙС. Пол можно дополнить здесь, если его не было в карточке.
        </Typography.Paragraph>
      )}
      <Form form={form} layout="vertical" requiredMark="optional">
        {kind === 'drivers' ? (
          <>
            <Form.Item name="full_name" label="ФИО" rules={[{ required: true, message: 'Укажите ФИО' }]}>
              <Input disabled={isPlatform} />
            </Form.Item>
            <Form.Item name="birth_date" label="Дата рождения">
              <DatePicker format="DD.MM.YYYY" style={{ width: '100%' }} disabled={isPlatform} />
            </Form.Item>
            <Form.Item name="gender" label="Пол">
              <Radio.Group optionType="button" options={[{ value: 'M', label: 'М' }, { value: 'F', label: 'Ж' }]} />
            </Form.Item>
            <Form.Item name="snils" label="СНИЛС"><Input /></Form.Item>
          </>
        ) : (
          <>
            <Form.Item name="brand" label="Марка" rules={[{ required: true, message: 'Укажите марку' }]}><Input /></Form.Item>
            <Form.Item name="model" label="Модель" rules={[{ required: true, message: 'Укажите модель' }]}><Input /></Form.Item>
            <Form.Item name="plate" label="Госномер" rules={[{ required: true, message: 'Укажите госномер' }]}><Input /></Form.Item>
            <Form.Item name="vehicle_type" label="Тип ТС"><Input /></Form.Item>
          </>
        )}
      </Form>
    </Modal>
  )
}
