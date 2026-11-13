import { useEffect } from 'react'
import { Space, Tag, Tooltip, Typography, Table, Input, Select, Button } from 'antd'
import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import type { OrganizationFull } from '../../../shared/types/api.types'
import { formatDate } from '../../../shared/utils/labels'
import { useOrganizations } from '../hooks/useOrganizations'
import { OrganizationFormModal } from './OrganizationFormModal'

const CONTRACT = { med: 'Мед', tech: 'Тех', medtech: 'Медтех' } as const
const ORIGIN = { platform: 'Платформа', manual: 'Вручную' } as const

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
      {o.epl_details?.daily_limit_left === 0 && (
        <Tooltip title="Восстановится в полночь, на формат работы не влияет">
          <Tag color="warning">Лимит ЭПЛ на сегодня исчерпан</Tag>
        </Tooltip>
      )}
    </Space>
  )
}

export function OrganizationsTab({
  canManage,
  startCreate,
  onCreateConsumed,
}: {
  canManage: boolean
  startCreate?: boolean
  onCreateConsumed?: () => void
}) {
  const {
    qInput, setQInput,
    origin, setOrigin,
    page, setPage,
    data, loading,
    editing, setEditing,
    saving, save
  } = useOrganizations()

  useEffect(() => {
    if (startCreate) {
      setEditing('new')
      onCreateConsumed?.()
    }
  }, [startCreate, setEditing, onCreateConsumed])

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Space wrap className="filterBar">
        <Input.Search
          allowClear
          placeholder="Название или ИНН"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          onSearch={(v) => setQInput(v)}
        />
        <Select allowClear placeholder="Источник" value={origin} onChange={(v) => { setOrigin(v); setPage(1) }}
          options={[{ value: 'platform', label: 'Платформа' }, { value: 'manual', label: 'Добавлены вручную' }]} />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing('new')}>
            Добавить организацию
          </Button>
        )}
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
              {!o.is_active && <Typography.Text type="secondary">неактивна</Typography.Text>}
            </Space>
          ) },
          { title: 'ИНН', dataIndex: 'inn', width: 130 },
          { title: 'Формат работы', key: 'format', width: 230, render: (_: unknown, o: OrganizationFull) => <FormatCell o={o} /> },
          { title: 'Договор', key: 'contract', width: 170, render: (_: unknown, o: OrganizationFull) =>
              `${o.contract_type ? CONTRACT[o.contract_type] : 'Медтех'}${o.contract_until ? ` до ${formatDate(o.contract_until)}` : ''}` },
          { title: 'Источник', dataIndex: 'origin', width: 110, render: (v: OrganizationFull['origin']) => <Tag bordered={false}>{ORIGIN[v]}</Tag> },
          { title: '', key: 'edit', width: 60, render: (_: unknown, o: OrganizationFull) =>
              canManage ? <Button size="small" type="text" icon={<EditOutlined />} aria-label="Изменить" onClick={() => setEditing(o)} /> : null },
        ]}
      />
      <OrganizationFormModal
        editing={editing}
        saving={saving}
        onClose={() => setEditing(null)}
        onSave={save}
      />
    </Space>
  )
}
