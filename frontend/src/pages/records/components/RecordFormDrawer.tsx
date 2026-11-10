import { useEffect, useState } from 'react'
import { App, Button, DatePicker, Drawer, Form, Input, InputNumber, Radio, Space } from 'antd'
import type { Dayjs } from 'dayjs'
import { fromPickerValue, nowForPicker, toPickerValue } from '../../../shared/utils/time'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { AnyRecord, Kind, MedicalRecord, TechnicalRecord } from '../../../shared/types/api.types'
import { useAuth } from '../../../core/auth/useAuth'
import { DriverSelect, OrganizationSelect, SpecialistSelect, VehicleSelect } from '../../../shared/components/CatalogSelects'

interface Props {
  kind: Kind
  open: boolean
  record: AnyRecord | null
  onClose: () => void
  onSaved: () => void
}

/** Добавление и правка записи. По ТЗ поля предзаполнены, результат осмотра выбирается вручную. */
export function RecordFormDrawer({ kind, open, record, onClose, onSaved }: Props) {
  const { user } = useAuth()
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [timeHint, setTimeHint] = useState<string | null>(null)
  const [timeTouched, setTimeTouched] = useState(false)
  const isEdit = Boolean(record)
  const isSpecialist = user?.role === 'medic' || user?.role === 'mechanic'
  const organizationId = Form.useWatch('organization_id', form) as string | undefined
  const driverId = Form.useWatch('driver_id', form) as string | undefined
  const vehicleId = Form.useWatch('vehicle_id', form) as string | undefined
  const phase = Form.useWatch('phase', form) as string | undefined

  useEffect(() => {
    if (!open) return
    setTimeHint(null)
    setTimeTouched(false)
    form.resetFields()
    if (record) {
      form.setFieldsValue({ ...record, performed_at: toPickerValue(record.performed_at) })
    } else if (kind === 'medical') {
      form.setFieldsValue({
        performed_at: nowForPicker(),
        phase: 'pre',
        complaints: 'отсутствуют',
        bp_systolic: 120,
        bp_diastolic: 80,
        pulse: 72,
        temperature: 36.6,
        alcohol_permille: 0,
        harmful_factors: 'absent',
      })
    } else {
      form.setFieldsValue({ performed_at: nowForPicker() })
    }
  }, [open, record, kind, form])

  // «Стандартное время» (ТЗ): для повторной записи подставляется время предыдущей по водителю или ТС
  useEffect(() => {
    if (!open || isEdit || timeTouched) return
    const subject = kind === 'medical' ? driverId : vehicleId
    if (!subject) return
    const params: Record<string, string> =
      kind === 'medical' ? { driver_id: subject, ...(phase ? { phase } : {}) } : { vehicle_id: subject }
    let cancelled = false
    JournalsService.getStandardTime(kind, params)
      .then(({ time }) => {
        if (cancelled || !time) return
        const [h, m] = time.split(':').map(Number)
        const current = (form.getFieldValue('performed_at') as Dayjs | undefined) ?? nowForPicker()
        form.setFieldValue('performed_at', current.hour(h).minute(m).second(0))
        setTimeHint(`Подставлено время предыдущей записи: ${time}`)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [open, isEdit, timeTouched, kind, driverId, vehicleId, phase, form])

  const submit = async () => {
    const values = await form.validateFields()
    const body: Record<string, unknown> = {
      ...values,
      performed_at: fromPickerValue(values.performed_at as Dayjs),
      note: values.note?.trim() ? values.note.trim() : null,
    }
    setSaving(true)
    try {
      if (record) await JournalsService.updateRecord(kind, record.id, body)
      else await JournalsService.createRecord(kind, body)
      message.success(record ? 'Изменения сохранены' : 'Запись добавлена')
      onSaved()
    } catch (err) {
      message.error(ApiErrorUtils.getMessage(err, 'Не удалось сохранить запись'))
    } finally {
      setSaving(false)
    }
  }

  const harmful = Form.useWatch('harmful_factors', form)

  return (
    <Drawer
      title={isEdit ? 'Изменить запись' : kind === 'medical' ? 'Новый медосмотр' : 'Новый техконтроль'}
      open={open}
      onClose={onClose}
      size="large"
      destroyOnHidden
      footer={
        <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
          <Button onClick={onClose}>Отмена</Button>
          <Button type="primary" loading={saving} onClick={() => void submit()}>
            {isEdit ? 'Сохранить' : 'Добавить запись'}
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional">
        <Form.Item name="organization_id" label="Организация" rules={[{ required: true, message: 'Выберите организацию' }]}>
          <OrganizationSelect
            onChange={(value) => {
              form.setFieldsValue({ organization_id: value, driver_id: undefined, vehicle_id: undefined })
            }}
          />
        </Form.Item>

        {kind === 'medical' ? (
          <Form.Item name="driver_id" label="Водитель" rules={[{ required: true, message: 'Выберите водителя' }]}>
            <DriverSelect organizationId={organizationId} />
          </Form.Item>
        ) : (
          <>
            <Form.Item name="vehicle_id" label="Транспортное средство" rules={[{ required: true, message: 'Выберите ТС' }]}>
              <VehicleSelect organizationId={organizationId} />
            </Form.Item>
            <Form.Item name="driver_id" label="Водитель">
              <DriverSelect organizationId={organizationId} allowClear />
            </Form.Item>
          </>
        )}

        {!isSpecialist && !isEdit ? (
          <Form.Item
            name="specialist_user_id"
            label={kind === 'medical' ? 'Медик, проводивший осмотр' : 'Механик, проводивший контроль'}
            rules={[{ required: true, message: 'Укажите, кто проводил осмотр' }]}
          >
            <SpecialistSelect role={kind === 'medical' ? 'medic' : 'mechanic'} />
          </Form.Item>
        ) : null}

        {kind === 'medical' ? (
          <Form.Item name="phase" label="Тип осмотра" rules={[{ required: true }]}>
            <Radio.Group optionType="button" options={[{ value: 'pre', label: 'Предрейсовый' }, { value: 'post', label: 'Послерейсовый' }]} />
          </Form.Item>
        ) : null}

        <Form.Item
          name="performed_at"
          label="Дата и время (по Москве)"
          rules={[{ required: true, message: 'Укажите дату и время' }]}
          extra={timeHint ?? undefined}
        >
          <DatePicker
            showTime={{ format: 'HH:mm' }}
            format="DD.MM.YYYY HH:mm"
            style={{ width: '100%' }}
            onChange={() => {
              setTimeTouched(true)
              setTimeHint(null)
            }}
          />
        </Form.Item>

        {kind === 'medical' ? (
          <>
            <Form.Item name="complaints" label="Жалобы, анамнез" rules={[{ required: true, message: 'Заполните поле' }]}>
              <Input />
            </Form.Item>
            <Space.Compact block style={{ gap: 12 }}>
              <Form.Item name="bp_systolic" label="АД, верхнее" rules={[{ required: true }]} style={{ flex: 1 }}>
                <InputNumber min={50} max={300} style={{ width: '100%' }} suffix="мм рт. ст." />
              </Form.Item>
              <Form.Item name="bp_diastolic" label="АД, нижнее" rules={[{ required: true }]} style={{ flex: 1 }}>
                <InputNumber min={30} max={200} style={{ width: '100%' }} suffix="мм рт. ст." />
              </Form.Item>
            </Space.Compact>
            <Space.Compact block style={{ gap: 12 }}>
              <Form.Item name="pulse" label="Пульс" rules={[{ required: true }]} style={{ flex: 1 }}>
                <InputNumber min={30} max={220} style={{ width: '100%' }} suffix="уд/мин" />
              </Form.Item>
              <Form.Item name="temperature" label="Температура" rules={[{ required: true }]} style={{ flex: 1 }}>
                <InputNumber min={34} max={42} step={0.1} precision={1} style={{ width: '100%' }} suffix="°C" />
              </Form.Item>
              <Form.Item name="alcohol_permille" label="Проба на алкоголь" rules={[{ required: true }]} style={{ flex: 1 }}>
                <InputNumber min={0} max={5} step={0.01} precision={2} style={{ width: '100%' }} suffix="‰" />
              </Form.Item>
            </Space.Compact>
            <Form.Item name="harmful_factors" label="Вредные производственные факторы">
              <Radio.Group optionType="button" options={[{ value: 'absent', label: 'Отсутствуют' }, { value: 'detected', label: 'Выявлены' }]} />
            </Form.Item>
            {harmful === 'detected' ? (
              <Form.Item name="harmful_factors_note" label="Какие признаки выявлены" rules={[{ required: true, message: 'Опишите признаки' }]}>
                <Input.TextArea rows={2} />
              </Form.Item>
            ) : null}
          </>
        ) : (
          <Form.Item name="odometer" label="Показания одометра" rules={[{ required: true, message: 'Укажите показания' }]}>
            <InputNumber min={0} style={{ width: '100%' }} suffix="км" />
          </Form.Item>
        )}

        <Form.Item name="result" label={kind === 'medical' ? 'Заключение' : 'Результат'} rules={[{ required: true, message: 'Выберите результат' }]}>
          <Radio.Group optionType="button" options={[{ value: 'admitted', label: 'Допущен' }, { value: 'not_admitted', label: 'Не допущен' }]} />
        </Form.Item>

        <Form.Item
          name="note"
          label="Примечание"
          extra="Запись с примечанием подписать нельзя: сначала снимите примечание"
        >
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
      </Form>
    </Drawer>
  )
}

export type { MedicalRecord, TechnicalRecord }
