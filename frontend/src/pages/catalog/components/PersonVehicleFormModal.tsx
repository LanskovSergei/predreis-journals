import { useEffect } from 'react'
import { Modal, Form, Input, DatePicker, Radio } from 'antd'

interface Props {
  kind: 'drivers' | 'vehicles'
  adding: boolean
  saving: boolean
  onClose: () => void
  onSave: (values: any) => Promise<void>
}

export function PersonVehicleFormModal({ kind, adding, saving, onClose, onSave }: Props) {
  const [form] = Form.useForm()

  useEffect(() => {
    if (adding) {
      form.resetFields()
    }
  }, [adding, form])

  const handleOk = () => {
    form.validateFields().then(onSave).catch(() => {})
  }

  return (
    <Modal
      title={kind === 'drivers' ? 'Новый водитель' : 'Новое ТС'}
      open={adding}
      onCancel={onClose}
      onOk={handleOk}
      okText="Добавить"
      cancelText="Отмена"
      confirmLoading={saving}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark="optional">
        {kind === 'drivers' ? (
          <>
            <Form.Item name="full_name" label="ФИО" rules={[{ required: true, message: 'Укажите ФИО' }]}><Input /></Form.Item>
            <Form.Item name="birth_date" label="Дата рождения"><DatePicker format="DD.MM.YYYY" style={{ width: '100%' }} /></Form.Item>
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
