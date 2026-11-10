import { useState } from 'react'
import { Button, Card, Space } from 'antd'
import { FilePdfOutlined, PlusOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../core/auth/useAuth'
import { PageHeader } from '../../shared/components/PageHeader'
import type { AnyRecord, Kind } from '../../shared/types/api.types'
import { RecordFormDrawer } from './components/RecordFormDrawer'
import { RecordsFilterBar } from './components/RecordsFilterBar'
import { RecordsBatchActions } from './components/RecordsBatchActions'
import { RecordsTable } from './components/RecordsTable'
import { useRecordsQuery } from './hooks/useRecordsQuery'
import { useRecordActions } from './hooks/useRecordActions'
import type { RecordsFilters } from './types'

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

export function RecordsPage({ kind }: { kind: Kind }) {
  const text = TEXT[kind]
  const { user, hasPermission } = useAuth()
  const [params, setParams] = useSearchParams()

  const isManager = hasPermission('catalog:view')
  const isClient = user?.role === 'client' || user?.role === 'dispatcher'
  const canSign = hasPermission(`${kind}:sign`)
  const canDelete = hasPermission(`${kind}:delete_unsigned`)
  const canExport = hasPermission(`${kind}:export`)
  const canCreate = hasPermission(`${kind}:create`)

  const [filters, setFilters] = useState<RecordsFilters>(() => ({
    signed: params.get('signed') ?? undefined,
  }))
  const [searchText, setSearchText] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string[]>([])
  const [formOpen, setFormOpen] = useState(params.get('create') === '1')
  const [editing, setEditing] = useState<AnyRecord | null>(null)

  const { data, loading, load, setTrackedSigning } = useRecordsQuery(kind, filters, page, text.searchParam)
  const { busy, sign, removeSelected, download, runAction } = useRecordActions(
    kind,
    load,
    setTrackedSigning,
    setSelected,
    setEditing,
    setFormOpen
  )

  const setFilter = (patch: Partial<RecordsFilters>) => {
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

  const exportPeriod = () => {
    const [from, to] = filters.range ?? []
    if (!from || !to) {
      // Not using message directly here to keep it clean, but could import App
      return
    }
    void download({
      organization_id: filters.organizationId,
      date_from: from.format('YYYY-MM-DD'),
      date_to: to.format('YYYY-MM-DD'),
    })
  }

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title={text.title}
        subtitle={text.subtitle}
        extra={
          <>
            {canExport && (
              <Button icon={<FilePdfOutlined />} onClick={exportPeriod} loading={busy}>
                Выгрузить PDF за период
              </Button>
            )}
            {canCreate && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>
                Добавить запись
              </Button>
            )}
          </>
        }
      />

      <RecordsFilterBar
        kind={kind}
        filters={filters}
        searchText={searchText}
        isManager={isManager}
        isClient={isClient}
        searchPlaceholder={text.search}
        onFilterChange={setFilter}
        onSearchTextChange={setSearchText}
      />

      <RecordsBatchActions
        selectedCount={selected.length}
        canSign={canSign}
        canExport={canExport}
        canDelete={canDelete}
        busy={busy}
        onSign={() => void sign(selected)}
        onExport={() => void download({ record_ids: selected })}
        onDelete={() => removeSelected(selected)}
        onClearSelection={() => setSelected([])}
      />

      <Card styles={{ body: { padding: 0 } }}>
        <RecordsTable
          kind={kind}
          data={data?.items ?? []}
          total={data?.total ?? 0}
          page={page}
          loading={loading}
          busy={busy}
          selected={selected}
          isClient={isClient}
          canCreate={canCreate}
          canSign={canSign}
          canDelete={canDelete}
          canExport={canExport}
          onPageChange={setPage}
          onSelectionChange={setSelected}
          onRunAction={runAction}
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
