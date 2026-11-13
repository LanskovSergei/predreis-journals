import { useEffect, useState } from 'react'
import { App, Button, DatePicker, Drawer, Form, Input, InputNumber, Radio, Segmented, Space, TimePicker } from 'antd'
import type { Dayjs } from 'dayjs'
import { fromPickerValue, nowForPicker, toPickerValue } from '../../../shared/utils/time'
import { JournalsService } from '../../../core/api/journals.service'
import { ApiErrorUtils } from '../../../shared/utils/error.utils'
import type { AnyRecord, Kind, MedicalRecord, TechnicalRecord } from '../../../shared/types/api.types'
import { useAuth } from '../../../core/auth/useAuth'
import { DriverSelect, OrganizationSelect, SpecialistSelect, VehicleSelect } from '../../../shared/components/CatalogSelects'
import { MAX_PERIOD_DAYS, VITAL_FIELDS, randomVitals } from '../utils/vitals'

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
  const { message, modal } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [timeHint, setTimeHint] = useState<string | null>(null)
  const [timeTouched, setTimeTouched] = useState(false)
  // ТЗ: дата осмотра — один день или период (по записи на каждый день)
  const [mode, setMode] = useState<'day' | 'period' | 'days'>('day')
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
    setMode('day')
    form.resetFields()
    if (record) {
      form.setFieldsValue({ ...record, performed_at: toPickerValue(record.performed_at) })
    } else if (kind === 'medical') {
      form.setFieldsValue({
        performed_at: nowForPicker(),
        period_time: nowForPicker(),
        phase: 'pre',
        complaints: 'отсутствуют',
        ...randomVitals(),
        alcohol_permille: 0,
        harmful_factors: 'absent',
      })
    } else {
      form.setFieldsValue({ performed_at: nowForPicker(), period_time: nowForPicker() })
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
        form.setFieldValue('period_time', nowForPicker().hour(h).minute(m).second(0))
        setTimeHint(`Подставлено время предыдущей записи: ${time}`)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [open, isEdit, timeTouched, kind, driverId, vehicleId, phase, form])

  /** Период: по записи на каждый день с одним временем; показатели — свои у каждой, если их не правили. */
  const submitPeriod = async (values: Record<string, unknown>) => {
    let dates: Dayjs[]
    if (mode === 'days') {
      // отдельные дни: без повторов, по порядку
      const picked = [...((values.days as Dayjs[] | undefined) ?? [])].sort((a, b) => a.valueOf() - b.valueOf())
      dates = picked.filter((d, i) => i === 0 || !d.isSame(picked[i - 1], 'day'))
    } else {
      const [from, to] = values.period as [Dayjs, Dayjs]
      const count = to.startOf('day').diff(from.startOf('day'), 'day') + 1
      dates = Array.from({ length: count }, (_, i) => from.add(i, 'day'))
    }
    if (dates.length > MAX_PERIOD_DAYS) {
      message.error(`За раз — не больше ${MAX_PERIOD_DAYS} дней`)
      return
    }
    const time = values.period_time as Dayjs
    const vitalsEdited = kind === 'medical' && form.isFieldsTouched(VITAL_FIELDS)
    const { period: _period, period_time: _time, days: _days, ...base } = values
    void _period
    void _time
    void _days
    setSaving(true)
    let created = 0
    const failed: string[] = []
    try {
      for (const date of dates) {
        const day = date.hour(time.hour()).minute(time.minute()).second(0)
        const body: Record<string, unknown> = {
          ...base,
          ...(kind === 'medical' && !vitalsEdited ? randomVitals() : {}),
          performed_at: fromPickerValue(day),
          note: typeof base.note === 'string' && base.note.trim() ? base.note.trim() : null,
        }
        try {
          await JournalsService.createRecord(kind, body)
          created += 1
        } catch (err) {
          failed.push(`${day.format('DD.MM.YYYY')}: ${ApiErrorUtils.getMessage(err, 'не удалось сохранить')}`)
        }
      }
    } finally {
      setSaving(false)
    }
    if (failed.length) {
      modal.warning({
        title: `Добавлено записей: ${created}, не получилось: ${failed.length}`,
        content: (
          <ul style={{ paddingLeft: 18, margin: 0 }}>
            {failed.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        ),
      })
    } else {
      message.success(`Добавлено записей: ${created}`)
    }
    if (created > 0) onSaved()
  }

  const submit = async () => {
    const values = await form.validateFields()
    if (!record && mode !== 'day') {
      await submitPeriod(values)
      return
    }
    const { period: _p, period_time: _t, days: _d, ...single } = values
    void _p
    void _t
    void _d
    const body: Record<string, unknown> = {
      ...single,
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

        {!isEdit ? (
          <Form.Item label="Дата осмотра" required>
            <Segmented
              value={mode}
              onChange={(v) => setMode(v as 'day' | 'period' | 'days')}
              options={[
                { value: 'day', label: 'Один день' },
                { value: 'period', label: 'Период' },
                { value: 'days', label: 'Отдельные дни' },
              ]}
            />
          </Form.Item>
        ) : null}

        {mode === 'day' || isEdit ? (
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
        ) : (
          <Space.Compact block style={{ gap: 12 }}>
            {mode === 'period' ? (
              <Form.Item
                name="period"
                label="Период"
                rules={[{ required: true, message: 'Выберите период' }]}
                extra={`По записи на каждый день, не больше ${MAX_PERIOD_DAYS}`}
                style={{ flex: 2 }}
              >
                <DatePicker.RangePicker format="DD.MM.YYYY" style={{ width: '100%' }} placeholder={['С даты', 'По дату']} />
              </Form.Item>
            ) : (
              <Form.Item
                name="days"
                label="Дни"
                rules={[{ required: true, message: 'Отметьте дни в календаре' }]}
                extra={`Отметьте нужные дни; повторный щелчок снимает отметку. Не больше ${MAX_PERIOD_DAYS}`}
                style={{ flex: 2 }}
              >
                <DatePicker multiple format="DD.MM.YYYY" maxTagCount="responsive" style={{ width: '100%' }} placeholder="Выберите дни" />
              </Form.Item>
            )}
            <Form.Item
              name="period_time"
              label="Время (по Москве)"
              rules={[{ required: true, message: 'Укажите время' }]}
              extra={timeHint ?? undefined}
              style={{ flex: 1 }}
            >
              <TimePicker
                format="HH:mm"
                style={{ width: '100%' }}
                onChange={() => {
                  setTimeTouched(true)
                  setTimeHint(null)
                }}
              />
            </Form.Item>
          </Space.Compact>
        )}

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
