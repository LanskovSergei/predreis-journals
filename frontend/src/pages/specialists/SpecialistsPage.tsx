import { Alert, Card, Segmented, Space, Table, Tag } from 'antd'
import type { SpecialistRow } from '../../shared/types/api.types'
import { PageHeader } from '../../shared/components/PageHeader'
import { formatDate } from '../../shared/utils/labels'
import { useSpecialists } from './hooks/useSpecialists'

const CERT = {
  active: { label: 'Действует', color: 'success' },
  expired: { label: 'Истёк', color: 'error' },
  missing: { label: 'Нет сертификата', color: 'default' },
} as const

export function SpecialistsPage() {
  const { role, setRole, data, loading } = useSpecialists()

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader title="Специалисты" subtitle="Сертификаты медиков и механиков для подписи записей и записи, ждущие их подписи" />
      <Segmented
        value={role}
        onChange={(v) => setRole(v as 'medic' | 'mechanic')}
        options={[
          { value: 'medic', label: 'Медики' },
          { value: 'mechanic', label: 'Механики' },
        ]}
      />
      {data && !data.certificates_available && (
        <Alert type="warning" showIcon title="Сведения о сертификатах сейчас недоступны: ПРЕДРЕЙС не ответил. Статусы могут быть неполными." />
      )}
      <Card styles={{ body: { padding: 0 } }}>
        <Table<SpecialistRow>
          rowKey="user_id"
          loading={loading}
          dataSource={data?.items ?? []}
          scroll={{ x: 760 }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: 'Специалистов нет' }}
          columns={[
            { title: 'ФИО', dataIndex: 'full_name' },
            {
              title: 'Сертификат',
              key: 'status',
              width: 220,
              render: (_: unknown, s: SpecialistRow) => (
                <Space size={4} wrap>
                  <Tag color={CERT[s.status].color}>{CERT[s.status].label}</Tag>
                  {s.expiring_soon && <Tag color="warning">Скоро истекает</Tag>}
                </Space>
              ),
            },
            { title: 'Действует до', dataIndex: 'valid_to', width: 130, render: (v: string | null) => formatDate(v) },
            { title: 'На подпись', key: 'to_sign', width: 110, render: (_: unknown, s: SpecialistRow) => s.records?.to_sign ?? '—' },
            { title: 'Подписано', key: 'signed', width: 110, render: (_: unknown, s: SpecialistRow) => s.records?.signed ?? '—' },
            { title: 'Всего', key: 'total', width: 90, render: (_: unknown, s: SpecialistRow) => s.records?.total ?? '—' },
          ]}
        />
      </Card>
    </Space>
  )
}
