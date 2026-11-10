import { Button, Dropdown, Space, Table, Tag, Tooltip, Typography, type MenuProps, type TableColumnsType } from 'antd'
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  MoreOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import type { AnyRecord, Kind, MedicalRecord, RecordAction, TechnicalRecord } from '../../../shared/types/api.types'
import { formatDate, formatDateTime, phaseLabels, resultLabels, sourceLabels, statusLabels } from '../../../shared/utils/labels'
import { getDriverName, getOrgName, getVehicleLabel } from '../utils/recordLabels'
import { isSigning, PAGE_SIZE } from '../hooks/useRecordsQuery'

interface Props {
  kind: Kind
  data: AnyRecord[]
  total: number
  page: number
  loading: boolean
  busy: boolean
  selected: string[]
  isClient: boolean
  canCreate: boolean
  canSign: boolean
  canDelete: boolean
  canExport: boolean
  onPageChange: (page: number) => void
  onSelectionChange: (keys: string[]) => void
  onRunAction: (action: RecordAction, record: AnyRecord) => void
}

export function RecordsTable({
  kind,
  data,
  total,
  page,
  loading,
  busy,
  selected,
  isClient,
  canCreate,
  canSign,
  canDelete,
  canExport,
  onPageChange,
  onSelectionChange,
  onRunAction,
}: Props) {
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
      {r.deletion_pending && <Tag color="orange">На удалении</Tag>}
      {r.signing_status === 'failed' && r.signing_error && (
        <Tooltip title={r.signing_error}>
          <Tag color="error">Подпись не прошла</Tag>
        </Tooltip>
      )}
      {r.has_note && (
        <Tooltip title={r.note}>
          <ExclamationCircleOutlined style={{ color: '#ED6C02' }} aria-label="Есть примечание" />
        </Tooltip>
      )}
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

  const actionItems = (record: AnyRecord): MenuProps['items'] =>
    (record.actions ?? [])
      .filter((a) => a !== 'sign')
      .map((a) => ({
        key: a,
        danger: a === 'delete' || a === 'request_deletion',
        icon: {
          edit: <EditOutlined />,
          delete: <DeleteOutlined />,
          clear_note: <CheckCircleOutlined />,
          request_deletion: <DeleteOutlined />,
          sign: null,
        }[a],
        label: {
          edit: 'Изменить',
          delete: 'Удалить',
          clear_note: 'Снять примечание',
          request_deletion: 'Запросить удаление',
          sign: '',
        }[a],
        onClick: () => onRunAction(a, record),
      }))

  const columns: TableColumnsType<AnyRecord> = [
    { title: 'Дата и время', dataIndex: 'performed_at', width: 140, render: (v: string) => formatDateTime(v) },
    ...(kind === 'medical'
      ? [
          { title: 'Водитель', key: 'driver', render: (_: unknown, r: AnyRecord) => getDriverName(r) },
          { title: 'Осмотр', key: 'phase', width: 130, render: (_: unknown, r: AnyRecord) => phaseLabels[(r as MedicalRecord).phase] },
        ]
      : [
          { title: 'Транспортное средство', key: 'vehicle', render: (_: unknown, r: AnyRecord) => getVehicleLabel(r) },
          { title: 'Одометр', key: 'odometer', width: 110, render: (_: unknown, r: AnyRecord) => (r as TechnicalRecord).odometer?.toLocaleString('ru-RU') ?? '—' },
        ]),
    ...(isClient ? [] : [{ title: 'Организация', key: 'org', render: (_: unknown, r: AnyRecord) => getOrgName(r) }]),
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
          {r.actions?.includes('sign') && (
            <Button size="small" type="primary" ghost onClick={() => onRunAction('sign', r)} disabled={busy}>
              Подписать
            </Button>
          )}
          {(actionItems(r) ?? []).length > 0 && (
            <Dropdown menu={{ items: actionItems(r) }} trigger={['click']} placement="bottomRight">
              <Button size="small" type="text" icon={<MoreOutlined />} aria-label="Действия с записью" />
            </Dropdown>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Table<AnyRecord>
      rowKey="id"
      size="middle"
      loading={loading}
      columns={columns}
      dataSource={data}
      scroll={{ x: 960 }}
      rowClassName={(r) => (r.has_note ? 'row-with-note' : '')}
      rowSelection={
        canSign || canDelete || canExport
          ? { selectedRowKeys: selected, onChange: (keys) => onSelectionChange(keys as string[]), preserveSelectedRowKeys: true }
          : undefined
      }
      locale={{
        emptyText: canCreate ? 'Записей нет. Добавьте первую запись кнопкой «Добавить запись».' : 'Записей нет',
      }}
      pagination={{
        current: page,
        pageSize: PAGE_SIZE,
        total,
        showSizeChanger: false,
        showTotal: (totalCount) => `Всего: ${totalCount}`,
        onChange: onPageChange,
      }}
    />
  )
}
