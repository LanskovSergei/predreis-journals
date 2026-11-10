import { useCallback, useEffect, useState } from 'react'
import { App, Button, Card, DatePicker, Form, Input, Modal, Radio, Select, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  createDriver,
  createOrganization,
  createVehicle,
  fetchDriversPage,
  fetchOrganizationsPage,
  fetchVehiclesPage,
  updateOrganization,
} from '@/api/journals'
import { errorMessage } from '@/api/client'
import type { DriverFull, OrganizationFull, Page, VehicleFull } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { OrganizationSelect } from '@/components/CatalogSelects'
import { PageHeader } from '@/components/PageHeader'
import { formatDate } from '@/utils/labels'

const CONTRACT = { med: 'Мед', tech: 'Тех', medtech: 'Медтех' } as const
const ORIGIN = { platform: 'Платформа', manual: 'Вручную' } as const

/** Почему организация «на бумаге» — по составляющим признака готовности из ПРЕДРЕЙС. */
function paperReasons(o: OrganizationFull): string[] {
  const d = o.epl_details
  if (o.origin === 'manual') return ['Организация добавлена вручную (нет на платформе)']
  if (!d) return []
  return [
    d.is_active === false ? 'организация отключена' : null,
    d.offer_accepted === false ? 'не подписан акцепт оферты' : null,
    d.mchd_active === false ? 'нет действующей МЧД' : null,
    d.contract_valid === false ? 'истёк договор' : null,
  ].filter((x): x is string => Boolean(x))
}

function FormatCell({ o }: { o: OrganizationFull }) {
  const reasons = paperReasons(o)
  return (
    <Space size={4} wrap>
      {o.work_format === 'epl' ? (
        <Tag color="success">На ЭПЛ</Tag>
      ) : (
        <Tooltip title={reasons.length ? reasons.join(', ') : undefined}>
          <Tag>На бумаге</Tag>
        </Tooltip>
      )}
      {o.epl_details?.daily_limit_left === 0 ? (
        <Tooltip title="Восстановится в полночь, на формат работы не влияет">
          <Tag color="warning">Лимит ЭПЛ на сегодня исчерпан</Tag>
        </Tooltip>
      ) : null}
    </Space>
  )
}

function OrganizationsTab({ canManage }: { canManage: boolean }) {
  const { message } = App.useApp()
  const [q, setQ] = useState('')
  const [origin, setOrigin] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<OrganizationFull> | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<OrganizationFull | 'new' | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await fetchOrganizationsPage({ q: q || undefined, origin, page, page_size: 10, only_active: false }))
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось загрузить организации'))
    } finally {
      setLoading(false)
    }
  }, [q, origin, page, message])

  useEffect(() => {
    void load()
  }, [load])

  const openForm = (o: OrganizationFull | 'new') => {
    setEditing(o)
    form.resetFields()
    if (o !== 'new') {
      form.setFieldsValue({
        ...o,
        contract_date: o.contract_date ? dayjs(o.contract_date) : undefined,
        contract_until: o.contract_until ? dayjs(o.contract_until) : undefined,
      })
    }
  }

  const save = async () => {
    const values = await form.validateFields()
    const body = {
      ...values,
      contract_date: values.contract_date ? values.contract_date.format('YYYY-MM-DD') : null,
      contract_until: values.contract_until ? values.contract_until.format('YYYY-MM-DD') : null,
    }
    setSaving(true)
    try {
      if (editing === 'new') await createOrganization(body)
      else if (editing?.origin === 'platform') {
        // реквизиты и срок договора организации из платформы ведёт ПРЕДРЕЙС — меняем только своё
        await updateOrganization(editing.id, { contract_type: values.contract_type ?? null, note: values.note ?? null })
      } else if (editing) await updateOrganization(editing.id, body)
      message.success(editing === 'new' ? 'Организация добавлена' : 'Изменения сохранены')
      setEditing(null)
      await load()
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось сохранить организацию'))
    } finally {
      setSaving(false)
    }
  }

  const isPlatform = editing !== 'new' && editing?.origin === 'platform'

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Space wrap className="filterBar">
        <Input.Search allowClear placeholder="Название или ИНН" onSearch={(v) => { setQ(v.trim()); setPage(1) }} />
        <Select allowClear placeholder="Источник" value={origin} onChange={(v) => { setOrigin(v); setPage(1) }}
          options={[{ value: 'platform', label: 'Платформа' }, { value: 'manual', label: 'Добавлены вручную' }]} />
        {canManage ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm('new')}>
            Добавить организацию
          </Button>
        ) : null}
      </Space>
      <Table<OrganizationFull>
        rowKey="id"
        loading={loading}
        dataSource={data?.items ?? []}
        scroll={{ x: 960 }}
        pagination={{ current: page, pageSize: 10, total: data?.total ?? 0, showSizeChanger: false, onChange: setPage, showTotal: (t) => `Всего: ${t}` }}
        locale={{ emptyText: 'Организаций не найдено' }}
        columns={[
          { title: 'Организация', key: 'name', render: (_: unknown, o: OrganizationFull) => (
            <Space orientation="vertical" size={0}>
              <span>{o.short_name || o.name}</span>
              {!o.is_active ? <Typography.Text type="secondary">неактивна</Typography.Text> : null}
            </Space>
          ) },
          { title: 'ИНН', dataIndex: 'inn', width: 130 },
          { title: 'Формат работы', key: 'format', width: 230, render: (_: unknown, o: OrganizationFull) => <FormatCell o={o} /> },
          { title: 'Договор', key: 'contract', width: 170, render: (_: unknown, o: OrganizationFull) =>
              `${o.contract_type ? CONTRACT[o.contract_type] : 'Медтех'}${o.contract_until ? ` до ${formatDate(o.contract_until)}` : ''}` },
          { title: 'Источник', dataIndex: 'origin', width: 110, render: (v: OrganizationFull['origin']) => <Tag bordered={false}>{ORIGIN[v]}</Tag> },
          { title: '', key: 'edit', width: 60, render: (_: unknown, o: OrganizationFull) =>
              canManage ? <Button size="small" type="text" icon={<EditOutlined />} aria-label="Изменить" onClick={() => openForm(o)} /> : null },
        ]}
      />
      <Modal
        title={editing === 'new' ? 'Новая организация' : 'Организация'}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={() => void save()}
        okText={editing === 'new' ? 'Добавить' : 'Сохранить'}
        cancelText="Отмена"
        confirmLoading={saving}
        destroyOnHidden
        width={640}
      >
        {isPlatform ? (
          <Typography.Paragraph type="secondary">
            Реквизиты и срок договора организации из платформы ведёт ПРЕДРЕЙС. Здесь меняются только вид договора и примечание.
          </Typography.Paragraph>
        ) : null}
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
    </Space>
  )
}

function PeopleAndVehiclesTab({ kind, canManage }: { kind: 'drivers' | 'vehicles'; canManage: boolean }) {
  const { message } = App.useApp()
  const [orgId, setOrgId] = useState<string | undefined>()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<DriverFull | VehicleFull> | null>(null)
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    if (!orgId) {
      setData(null)
      return
    }
    setLoading(true)
    try {
      const params = { organization_id: orgId, q: q || undefined, page, page_size: 10 }
      setData(kind === 'drivers' ? await fetchDriversPage(params) : await fetchVehiclesPage(params))
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось загрузить список'))
    } finally {
      setLoading(false)
    }
  }, [orgId, q, page, kind, message])

  useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (kind === 'drivers') {
        await createDriver({ ...values, organization_id: orgId, birth_date: values.birth_date ? values.birth_date.format('YYYY-MM-DD') : null })
      } else {
        await createVehicle({ ...values, organization_id: orgId })
      }
      message.success(kind === 'drivers' ? 'Водитель добавлен' : 'ТС добавлено')
      setAdding(false)
      form.resetFields()
      await load()
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось сохранить'))
    } finally {
      setSaving(false)
    }
  }

  const driverColumns = [
    { title: 'ФИО', dataIndex: 'full_name' },
    { title: 'Дата рождения', dataIndex: 'birth_date', width: 140, render: (v: string | null) => formatDate(v) },
    { title: 'Источник', dataIndex: 'origin', width: 120, render: (v: 'platform' | 'manual') => <Tag bordered={false}>{ORIGIN[v]}</Tag> },
  ]
  const vehicleColumns = [
    { title: 'Марка и модель', key: 'bm', render: (_: unknown, v: VehicleFull) => `${v.brand} ${v.model}` },
    { title: 'Госномер', dataIndex: 'plate', width: 140 },
    { title: 'Тип', dataIndex: 'vehicle_type', width: 160, render: (v: string | null) => v || '—' },
    { title: 'Источник', dataIndex: 'origin', width: 120, render: (v: 'platform' | 'manual') => <Tag bordered={false}>{ORIGIN[v]}</Tag> },
  ]

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Space wrap className="filterBar">
        <OrganizationSelect allowClear value={orgId} onChange={(v) => { setOrgId(v); setPage(1) }} placeholder="Выберите организацию" />
        <Input.Search allowClear placeholder={kind === 'drivers' ? 'ФИО' : 'Марка, модель или госномер'} disabled={!orgId}
          onSearch={(v) => { setQ(v.trim()); setPage(1) }} />
        {canManage ? (
          <Button type="primary" icon={<PlusOutlined />} disabled={!orgId} onClick={() => setAdding(true)}>
            {kind === 'drivers' ? 'Добавить водителя' : 'Добавить ТС'}
          </Button>
        ) : null}
      </Space>
      <Table<DriverFull | VehicleFull>
        rowKey="id"
        loading={loading}
        dataSource={data?.items ?? []}
        // @ts-expect-error колонки разных типов в одной таблице
        columns={kind === 'drivers' ? driverColumns : vehicleColumns}
        pagination={{ current: page, pageSize: 10, total: data?.total ?? 0, showSizeChanger: false, onChange: setPage, showTotal: (t) => `Всего: ${t}` }}
        locale={{ emptyText: orgId ? 'Список пуст' : 'Выберите организацию, чтобы увидеть список' }}
      />
      <Modal
        title={kind === 'drivers' ? 'Новый водитель' : 'Новое ТС'}
        open={adding}
        onCancel={() => setAdding(false)}
        onOk={() => void save()}
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
    </Space>
  )
}

/** Общий каталог: организации из ПРЕДРЕЙС и добавленные вручную, их водители и ТС. */
export function CatalogPage() {
  const { can } = useAuth()
  const canManage = can('catalog:manage')
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="Каталог"
        subtitle="Организации из ПРЕДРЕЙС и бумажные клиенты, добавленные вручную. Карточки объединяются автоматически, когда клиент регистрируется на платформе."
      />
      <Card>
        <Tabs
          items={[
            { key: 'orgs', label: 'Организации', children: <OrganizationsTab canManage={canManage} /> },
            { key: 'drivers', label: 'Водители', children: <PeopleAndVehiclesTab kind="drivers" canManage={canManage} /> },
            { key: 'vehicles', label: 'Транспортные средства', children: <PeopleAndVehiclesTab kind="vehicles" canManage={canManage} /> },
          ]}
        />
      </Card>
    </Space>
  )
}
