import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Card,
  DatePicker,
  Dropdown,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  type MenuProps,
  type TableColumnsType,
} from 'antd'
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  FilePdfOutlined,
  MoreOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { useSearchParams } from 'react-router-dom'
import {
  clearNote,
  deleteRecord,
  deleteRecords,
  exportPdf,
  fetchRecords,
  requestDeletion,
  signRecords,
} from '@/api/journals'
import { errorMessage } from '@/api/client'
import type { AnyRecord, Kind, MedicalRecord, Page, RecordAction, TechnicalRecord } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { OrganizationSelect } from '@/components/CatalogSelects'
import { PageHeader } from '@/components/PageHeader'
import { formatDate, formatDateTime, phaseLabels, resultLabels, saveBlob, sourceLabels, statusLabels } from '@/utils/labels'
import { RecordFormDrawer } from './RecordFormDrawer'

const TEXT = {
  medical: {
    title: 'Медосмотры',
    subtitle: 'Предрейсовые и послерейсовые медицинские осмотры водителей',
    search: 'ФИО водителя',
    searchParam: 'driver_name',
  },
  technical: {
    title: 'Техконтроль',
    subtitle: 'Контроль технического состояния транспортных средств',
    search: 'Марка, модель или госномер',
    searchParam: 'vehicle',
  },
} as const

const PAGE_SIZE = 10 // ТЗ: одна страница — 10 записей

interface Filters {
  organizationId?: string
  range?: [Dayjs | null, Dayjs | null] | null
  text?: string
  result?: string
  signed?: string
  note?: string
}

const driverName = (r: AnyRecord) =>
  (r as MedicalRecord).driver_full_name ?? r.snapshot?.driver?.full_name ?? '—'
const vehicleLabel = (r: AnyRecord) => {
  const v = r.snapshot?.vehicle
  return v ? `${v.brand ?? ''} ${v.model ?? ''}, ${v.plate ?? ''}`.trim() : '—'
}
const orgName = (r: AnyRecord) => r.snapshot?.organization?.short_name || r.snapshot?.organization?.name || '—'
const isSigning = (r: AnyRecord) => r.signing_status === 'queued' || r.signing_status === 'pending'

/** Архив записей журнала (общий для медосмотров и техконтроля). */
export function RecordsPage({ kind }: { kind: Kind }) {
  const text = TEXT[kind]
  const { me, can } = useAuth()
  const { message, modal } = App.useApp()
  const [params, setParams] = useSearchParams()
  const isManager = can('catalog:view')
  const isClient = me?.role === 'client' || me?.role === 'dispatcher'

  const [filters, setFilters] = useState<Filters>(() => ({
    signed: params.get('signed') ?? undefined,
  }))
  const [searchText, setSearchText] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<AnyRecord> | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string[]>([])
  const [formOpen, setFormOpen] = useState(params.get('create') === '1')
  const [editing, setEditing] = useState<AnyRecord | null>(null)
  const [busy, setBusy] = useState(false)

  const queryParams = useMemo(() => {
    const q: Record<string, unknown> = { page, page_size: PAGE_SIZE }
    if (filters.organizationId) q.organization_id = filters.organizationId
    if (filters.range?.[0]) q.date_from = filters.range[0].format('YYYY-MM-DD')
    if (filters.range?.[1]) q.date_to = filters.range[1].format('YYYY-MM-DD')
    if (filters.text) q[text.searchParam] = filters.text
    if (filters.result) q.result = filters.result
    if (filters.signed) q.is_signed = filters.signed === '1'
    if (filters.note) q.has_note = filters.note === '1'
    return q
  }, [filters, page, text.searchParam])

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true)
      try {
        setData(await fetchRecords(kind, queryParams))
      } catch (err) {
        if (!quiet) message.error(errorMessage(err, 'Не удалось загрузить записи'))
      } finally {
        if (!quiet) setLoading(false)
      }
    },
    [kind, queryParams, message],
  )

  useEffect(() => {
    void load()
  }, [load])

  // Пока по записям идёт подпись, список сам обновляется раз в 5 секунд
  useEffect(() => {
    if (!data?.items.some(isSigning)) return
    const timer = window.setInterval(() => void load(true), 5000)
    return () => window.clearInterval(timer)
  }, [data, load])

  const setFilter = (patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
    setSelected([])
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditing(null)
    if (params.get('create')) {
      params.delete('create')
      setParams(params, { replace: true })
    }
  }

  const reportBatch = (title: string, okCount: number, results: { ok: boolean; message?: string | null }[]) => {
    const failed = results.filter((r) => !r.ok)
    if (failed.length === 0) {
      message.success(`${title}: ${okCount}`)
      return
    }
    modal.warning({
      title: `${title}: ${okCount}, не получилось: ${failed.length}`,
      content: (
        <ul style={{ paddingLeft: 18, margin: 0 }}>
          {[...new Set(failed.map((r) => r.message ?? 'Причина не указана'))].map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ),
    })
  }

  const sign = async (ids: string[]) => {
    setBusy(true)
    try {
      const res = await signRecords(kind, ids)
      reportBatch('Отправлено на подпись', res.signed, res.results)
      setSelected([])
      await load(true)
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось отправить на подпись'))
    } finally {
      setBusy(false)
    }
  }

  const removeSelected = () =>
    modal.confirm({
      title: `Удалить выбранные записи (${selected.length})?`,
      content: 'Удаляются только неподписанные записи. Действие нельзя отменить.',
      okText: 'Удалить',
      okButtonProps: { danger: true },
      cancelText: 'Отмена',
      onOk: async () => {
        try {
          const res = await deleteRecords(kind, selected)
          reportBatch('Удалено', res.deleted, res.results)
          setSelected([])
          await load(true)
        } catch (err) {
          message.error(errorMessage(err, 'Не удалось удалить записи'))
        }
      },
    })

  const download = async (body: Record<string, unknown>) => {
    setBusy(true)
    try {
      const { blob, filename } = await exportPdf(kind, body)
      saveBlob(blob, filename)
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось сформировать выгрузку'))
    } finally {
      setBusy(false)
    }
  }

  const exportPeriod = () => {
    const [from, to] = filters.range ?? []
    if (!from || !to) {
      message.info('Выберите период в фильтрах, чтобы выгрузить PDF')
      return
    }
    void download({
      organization_id: filters.organizationId,
      date_from: from.format('YYYY-MM-DD'),
      date_to: to.format('YYYY-MM-DD'),
    })
  }

  const runAction = (action: RecordAction, record: AnyRecord) => {
    if (action === 'sign') void sign([record.id])
    if (action === 'edit') {
      setEditing(record)
      setFormOpen(true)
    }
    if (action === 'clear_note') {
      modal.confirm({
        title: 'Снять примечание?',
        content: record.note,
        okText: 'Снять',
        cancelText: 'Отмена',
        onOk: async () => {
          try {
            await clearNote(kind, record.id)
            message.success('Примечание снято')
            await load(true)
          } catch (err) {
            message.error(errorMessage(err))
          }
        },
      })
    }
    if (action === 'delete') {
      modal.confirm({
        title: 'Удалить запись?',
        content: `${formatDateTime(record.performed_at)}, ${kind === 'medical' ? driverName(record) : vehicleLabel(record)}`,
        okText: 'Удалить',
        okButtonProps: { danger: true },
        cancelText: 'Отмена',
        onOk: async () => {
          try {
            await deleteRecord(kind, record.id)
            message.success('Запись удалена')
            await load(true)
          } catch (err) {
            message.error(errorMessage(err))
          }
        },
      })
    }
    if (action === 'request_deletion') {
      let reason = ''
      modal.confirm({
        title: 'Запросить удаление подписанной записи',
        content: (
          <Space orientation="vertical" style={{ width: '100%' }}>
            <Typography.Text type="secondary">
              Удаление подписанной записи подтверждает Админ или Суперадмин.
            </Typography.Text>
            <Input.TextArea rows={3} placeholder="Причина удаления" onChange={(e) => (reason = e.target.value)} />
          </Space>
        ),
        okText: 'Отправить запрос',
        cancelText: 'Отмена',
        onOk: async () => {
          try {
            await requestDeletion(kind, record.id, reason.trim())
            message.success('Запрос на удаление отправлен')
            await load(true)
          } catch (err) {
            message.error(errorMessage(err))
          }
        },
      })
    }
  }

  const actionItems = (record: AnyRecord): MenuProps['items'] =>
    (record.actions ?? [])
      .filter((a) => a !== 'sign')
      .map((a) => ({
        key: a,
        danger: a === 'delete' || a === 'request_deletion',
        icon: { edit: <EditOutlined />, delete: <DeleteOutlined />, clear_note: <CheckCircleOutlined />, request_deletion: <DeleteOutlined />, sign: null }[a],
        label: { edit: 'Изменить', delete: 'Удалить', clear_note: 'Снять примечание', request_deletion: 'Запросить удаление', sign: '' }[a],
        onClick: () => runAction(a, record),
      }))

  const statusCell = (r: AnyRecord) => (
    <Space size={4} wrap>
      {isSigning(r) ? (
        <Tag color="processing">Подписывается…</Tag>
      ) : (
        <Tag color={r.status === 'unsigned' ? 'default' : r.status === 'signed' ? 'blue' : 'purple'}>
          {statusLabels[r.status]}
        </Tag>
      )}
      <Tag bordered={false}>{sourceLabels[r.source]}</Tag>
      {r.deletion_pending ? <Tag color="orange">На удалении</Tag> : null}
      {r.signing_status === 'failed' && r.signing_error ? (
        <Tooltip title={r.signing_error}>
          <Tag color="error">Подпись не прошла</Tag>
        </Tooltip>
      ) : null}
      {r.has_note ? (
        <Tooltip title={r.note}>
          <ExclamationCircleOutlined style={{ color: '#ED6C02' }} aria-label="Есть примечание" />
        </Tooltip>
      ) : null}
    </Space>
  )

  const signatureCell = (r: AnyRecord) =>
    r.signature ? (
      <Tooltip
        title={
          <>
            Сертификат № {r.signature.cert_serial}
            <br />
            {r.signature.cert_subject}
            <br />
            Действителен с {formatDate(r.signature.cert_valid_from)} по {formatDate(r.signature.cert_valid_to)}
          </>
        }
      >
        <span>
          <SafetyCertificateOutlined style={{ color: '#2E7D32' }} />{' '}
          {r.signature.signed_at ? formatDate(r.signature.signed_at) : r.source === 'epl' ? 'Титул ЭПЛ' : 'Есть'}
        </span>
      </Tooltip>
    ) : (
      <Typography.Text type="secondary">—</Typography.Text>
    )

  const columns: TableColumnsType<AnyRecord> = [
    { title: 'Дата и время', dataIndex: 'performed_at', width: 140, render: (v: string) => formatDateTime(v) },
    ...(kind === 'medical'
      ? [
          { title: 'Водитель', key: 'driver', render: (_: unknown, r: AnyRecord) => driverName(r) },
          { title: 'Осмотр', key: 'phase', width: 130, render: (_: unknown, r: AnyRecord) => phaseLabels[(r as MedicalRecord).phase] },
        ]
      : [
          { title: 'Транспортное средство', key: 'vehicle', render: (_: unknown, r: AnyRecord) => vehicleLabel(r) },
          { title: 'Одометр', key: 'odometer', width: 110, render: (_: unknown, r: AnyRecord) => (r as TechnicalRecord).odometer?.toLocaleString('ru-RU') ?? '—' },
        ]),
    ...(isClient ? [] : [{ title: 'Организация', key: 'org', render: (_: unknown, r: AnyRecord) => orgName(r) }]),
    {
      title: kind === 'medical' ? 'Заключение' : 'Результат',
      dataIndex: 'result',
      width: 120,
      render: (v: AnyRecord['result']) => <Tag color={v === 'admitted' ? 'success' : 'error'}>{resultLabels[v]}</Tag>,
    },
    { title: 'Статус', key: 'status', render: (_: unknown, r: AnyRecord) => statusCell(r) },
    { title: 'Подпись', key: 'signature', width: 120, render: (_: unknown, r: AnyRecord) => signatureCell(r) },
    {
      title: '',
      key: 'actions',
      width: 150,
      align: 'right',
      render: (_: unknown, r: AnyRecord) => (
        <Space size={4}>
          {r.actions?.includes('sign') ? (
            <Button size="small" type="primary" ghost onClick={() => runAction('sign', r)} disabled={busy}>
              Подписать
            </Button>
          ) : null}
          {(actionItems(r) ?? []).length > 0 ? (
            <Dropdown menu={{ items: actionItems(r) }} trigger={['click']} placement="bottomRight">
              <Button size="small" type="text" icon={<MoreOutlined />} aria-label="Действия с записью" />
            </Dropdown>
          ) : null}
        </Space>
      ),
    },
  ]

  const canSign = can(`${kind}:sign`)
  const canDelete = can(`${kind}:delete_unsigned`)
  const canExport = can(`${kind}:export`)
  const canCreate = can(`${kind}:create`)

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title={text.title}
        subtitle={text.subtitle}
        extra={
          <>
            {canExport ? (
              <Button icon={<FilePdfOutlined />} onClick={exportPeriod} loading={busy}>
                Выгрузить PDF за период
              </Button>
            ) : null}
            {canCreate ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>
                Добавить запись
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <Space wrap className="filterBar">
          {isManager ? (
            <OrganizationSelect allowClear value={filters.organizationId} onChange={(v) => setFilter({ organizationId: v })} />
          ) : null}
          <DatePicker.RangePicker
            format="DD.MM.YYYY"
            value={filters.range ?? null}
            onChange={(values) => setFilter({ range: values as Filters['range'] })}
            placeholder={['С даты', 'По дату']}
          />
          <Input.Search
            allowClear
            placeholder={text.search}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value)
              if (!e.target.value) setFilter({ text: undefined })
            }}
            onSearch={(value) => {
              const v = value.trim()
              if (v && v.length < 3) {
                message.info('Введите хотя бы 3 символа')
                return
              }
              setFilter({ text: v || undefined })
            }}
          />
          <Select
            allowClear
            placeholder={kind === 'medical' ? 'Заключение' : 'Результат'}
            value={filters.result}
            onChange={(v) => setFilter({ result: v })}
            options={[
              { value: 'admitted', label: 'Допущен' },
              { value: 'not_admitted', label: 'Не допущен' },
            ]}
          />
          {!isClient ? (
            <Select
              allowClear
              placeholder="Подпись"
              value={filters.signed}
              onChange={(v) => setFilter({ signed: v })}
              options={[
                { value: '0', label: 'Не подписанные' },
                { value: '1', label: 'Подписанные' },
              ]}
            />
          ) : null}
          {!isClient ? (
            <Select
              allowClear
              placeholder="Примечание"
              value={filters.note}
              onChange={(v) => setFilter({ note: v })}
              options={[
                { value: '1', label: 'С примечанием' },
                { value: '0', label: 'Без примечания' },
              ]}
            />
          ) : null}
        </Space>
      </Card>

      {selected.length > 0 ? (
        <Card size="small">
          <Space wrap>
            <Typography.Text strong>Выбрано: {selected.length}</Typography.Text>
            {canSign ? (
              <Button type="primary" loading={busy} onClick={() => void sign(selected)} disabled={selected.length > 50}>
                Подписать
              </Button>
            ) : null}
            {canExport ? (
              <Button icon={<FilePdfOutlined />} loading={busy} onClick={() => void download({ record_ids: selected })}>
                Выгрузить PDF
              </Button>
            ) : null}
            {canDelete ? (
              <Button danger icon={<DeleteOutlined />} onClick={removeSelected}>
                Удалить
              </Button>
            ) : null}
            <Button type="text" onClick={() => setSelected([])}>
              Снять выбор
            </Button>
            {selected.length > 50 ? (
              <Typography.Text type="warning">За раз можно подписать до 50 записей</Typography.Text>
            ) : null}
          </Space>
        </Card>
      ) : null}

      <Card styles={{ body: { padding: 0 } }}>
        <Table<AnyRecord>
          rowKey="id"
          size="middle"
          loading={loading}
          columns={columns}
          dataSource={data?.items ?? []}
          scroll={{ x: 960 }}
          rowClassName={(r) => (r.has_note ? 'row-with-note' : '')}
          rowSelection={
            canSign || canDelete || canExport
              ? { selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]), preserveSelectedRowKeys: true }
              : undefined
          }
          locale={{
            emptyText: canCreate ? 'Записей нет. Добавьте первую запись кнопкой «Добавить запись».' : 'Записей нет',
          }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: data?.total ?? 0,
            showSizeChanger: false,
            showTotal: (total) => `Всего: ${total}`,
            onChange: setPage,
          }}
        />
      </Card>

      <RecordFormDrawer
        kind={kind}
        open={formOpen}
        record={editing}
        onClose={closeForm}
        onSaved={() => {
          closeForm()
          void load(true)
        }}
      />
    </Space>
  )
}

