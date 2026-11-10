import { Space, Tag, Table, Input, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { DriverFull, VehicleFull } from '../../../shared/types/api.types'
import { formatDate } from '../../../shared/utils/labels'
import { OrganizationSelect } from '../../../shared/components/CatalogSelects'
import { usePeopleAndVehicles } from '../hooks/usePeopleAndVehicles'
import { PersonVehicleFormModal } from './PersonVehicleFormModal'

const ORIGIN = { platform: 'Платформа', manual: 'Вручную' } as const

export function PeopleAndVehiclesTab({ kind, canManage }: { kind: 'drivers' | 'vehicles'; canManage: boolean }) {
  const {
    orgId, setOrgId,
    setQ,
    page, setPage,
    data, loading,
    adding, setAdding,
    saving, save
  } = usePeopleAndVehicles(kind)

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
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} disabled={!orgId} onClick={() => setAdding(true)}>
            {kind === 'drivers' ? 'Добавить водителя' : 'Добавить ТС'}
          </Button>
        )}
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
      <PersonVehicleFormModal
        kind={kind}
        adding={adding}
        saving={saving}
        onClose={() => setAdding(false)}
        onSave={save}
      />
    </Space>
  )
}
