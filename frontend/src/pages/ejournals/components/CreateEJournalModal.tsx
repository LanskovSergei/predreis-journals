import { useEffect } from 'react'
import { Modal, Form, Radio, DatePicker, Alert } from 'antd'
import { OrganizationSelect } from '../../../shared/components/CatalogSelects'
import type { Kind } from '../../../shared/types/api.types'
import { KIND_LABEL } from '../EJournalsPage'

interface Props {
  open: boolean
  creating: boolean
  buildKinds: Kind[]
  onClose: () => void
  onCreate: (values: any) => Promise<void>
}

export function CreateEJournalModal({ open, creating, buildKinds, onClose, onCreate }: Props) {
  const [form] = Form.useForm()

  useEffect(() => {
    if (open) {
      form.resetFields()
    }
  }, [open, form])

  const handleOk = () => {
    form.validateFields().then(onCreate).catch(() => {})
  }

  return (
    <Modal
      title="Сформировать электронный журнал"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="Сформировать"
      cancelText="Отмена"
      confirmLoading={creating}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="В журнал попадут подписанные записи за период, которые ещё не вошли в другой журнал."
      />
      <Form form={form} layout="vertical" initialValues={{ kind: buildKinds[0] }}>
        <Form.Item name="kind" label="Журнал" rules={[{ required: true }]}>
          <Radio.Group optionType="button" options={buildKinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
        </Form.Item>
        <Form.Item name="organization_id" label="Организация" rules={[{ required: true, message: 'Выберите организацию' }]}>
          <OrganizationSelect />
        </Form.Item>
        <Form.Item name="period" label="Период" rules={[{ required: true, message: 'Выберите период' }]}>
          <DatePicker.RangePicker format="DD.MM.YYYY" style={{ width: '100%' }} placeholder={['С даты', 'По дату']} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
