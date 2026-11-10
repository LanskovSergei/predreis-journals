import { useEffect, useState } from 'react'
import { Alert, App, Card, Segmented, Space, Table, Tag } from 'antd'
import { fetchSpecialistsList } from '@/api/journals'
import { errorMessage } from '@/api/client'
import type { SpecialistRow, SpecialistsList } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { formatDate } from '@/utils/labels'

const CERT = {
  active: { label: 'Действует', color: 'success' },
  expired: { label: 'Истёк', color: 'error' },
  missing: { label: 'Нет сертификата', color: 'default' },
} as const

/** Медики и механики: сертификаты для подписи и сколько записей ждут их подписи. */
export function SpecialistsPage() {
  const { message } = App.useApp()
  const [role, setRole] = useState<'medic' | 'mechanic'>('medic')
  const [data, setData] = useState<SpecialistsList | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchSpecialistsList(role)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && message.error(errorMessage(err, 'Не удалось загрузить специалистов')))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [role, message])

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
      {data && !data.certificates_available ? (
        <Alert type="warning" showIcon title="Сведения о сертификатах сейчас недоступны: ПРЕДРЕЙС не ответил. Статусы могут быть неполными." />
      ) : null}
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
                  {s.expiring_soon ? <Tag color="warning">Скоро истекает</Tag> : null}
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
