import { useEffect } from 'react'
import { Modal, Form, Input, DatePicker, Radio, Space, Typography } from 'antd'
import dayjs from 'dayjs'
import type { OrganizationFull } from '../../../shared/types/api.types'

interface Props {
  editing: OrganizationFull | 'new' | null
  saving: boolean
  onClose: () => void
  onSave: (values: any) => Promise<void>
}

export function OrganizationFormModal({ editing, saving, onClose, onSave }: Props) {
  const [form] = Form.useForm()
  const isPlatform = editing !== 'new' && editing?.origin === 'platform'

  useEffect(() => {
    if (!editing) return
    form.resetFields()
    if (editing !== 'new') {
      form.setFieldsValue({
        ...editing,
        contract_date: editing.contract_date ? dayjs(editing.contract_date) : undefined,
        contract_until: editing.contract_until ? dayjs(editing.contract_until) : undefined,
      })
    }
  }, [editing, form])

  const handleOk = () => {
    form.validateFields().then(onSave).catch(() => {})
  }

  return (
    <Modal
      title={editing === 'new' ? 'Новая организация' : 'Организация'}
      open={editing !== null}
      onCancel={onClose}
      onOk={handleOk}
      okText={editing === 'new' ? 'Добавить' : 'Сохранить'}
      cancelText="Отмена"
      confirmLoading={saving}
      destroyOnHidden
      width={640}
    >
      {isPlatform && (
        <Typography.Paragraph type="secondary">
          Реквизиты и срок договора организации из платформы ведёт ПРЕДРЕЙС. Здесь меняются только вид договора и примечание.
        </Typography.Paragraph>
      )}
      <Form form={form} layout="vertical" requiredMark="optional">
        <Form.Item name="inn" label="ИНН" rules={[{ required: true, message: 'Укажите ИНН' }]}>
          <Input disabled={isPlatform} maxLength={12} />
        </Form.Item>
        <Form.Item name="name" label="Полное название" rules={[{ required: true, message: 'Укажите название' }]}>
          <Input disabled={isPlatform} />
        </Form.Item>
        <Form.Item name="short_name" label="Краткое название">
          <Input disabled={isPlatform} />
        </Form.Item>
        <Space.Compact block style={{ gap: 12 }}>
          <Form.Item name="kpp" label="КПП" style={{ flex: 1 }}><Input disabled={isPlatform} /></Form.Item>
          <Form.Item name="ogrn" label="ОГРН" style={{ flex: 1 }}><Input disabled={isPlatform} /></Form.Item>
        </Space.Compact>
        <Form.Item name="legal_address" label="Юридический адрес"><Input disabled={isPlatform} /></Form.Item>
        <Form.Item name="contract_type" label="Вид договора" extra="«Мед» — только медосмотры, «Тех» — только техконтроль, «Медтех» — оба журнала">
          <Radio.Group optionType="button" options={[{ value: 'med', label: 'Мед' }, { value: 'tech', label: 'Тех' }, { value: 'medtech', label: 'Медтех' }]} />
        </Form.Item>
        <Space.Compact block style={{ gap: 12 }}>
          <Form.Item name="contract_number" label="Номер договора" style={{ flex: 1 }}><Input disabled={isPlatform} /></Form.Item>
          <Form.Item name="contract_date" label="Дата договора" style={{ flex: 1 }}><DatePicker format="DD.MM.YYYY" style={{ width: '100%' }} disabled={isPlatform} /></Form.Item>
          <Form.Item name="contract_until" label="Действует до" style={{ flex: 1 }}><DatePicker format="DD.MM.YYYY" style={{ width: '100%' }} disabled={isPlatform} /></Form.Item>
        </Space.Compact>
        <Form.Item name="note" label="Примечание"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}
