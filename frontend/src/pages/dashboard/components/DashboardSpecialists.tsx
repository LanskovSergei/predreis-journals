import { Button, Card, Col, Row, Space, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { JournalsService } from '../../../core/api/journals.service'
import type { SpecialistRow } from '../../../shared/types/api.types'

export function DashboardSpecialists() {
  const navigate = useNavigate()
  const [medics, setMedics] = useState<SpecialistRow[]>([])
  const [mechanics, setMechanics] = useState<SpecialistRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      JournalsService.getSpecialistsList('medic'),
      JournalsService.getSpecialistsList('mechanic'),
    ])
      .then(([m, t]) => {
        if (cancelled) return
        setMedics(m.items ?? [])
        setMechanics(t.items ?? [])
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const columns = [
    { title: 'ФИО', dataIndex: 'full_name' },
    {
      title: 'На подпись',
      width: 120,
      render: (_: unknown, s: SpecialistRow) => s.records?.to_sign ?? 0,
    },
    {
      title: 'Подписано',
      width: 120,
      render: (_: unknown, s: SpecialistRow) => s.records?.signed ?? 0,
    },
    {
      title: 'Из них ЭПЛ',
      width: 120,
      render: (_: unknown, s: SpecialistRow) => s.records?.epl ?? 0,
    },
  ]

  return (
    <Card
      title="Специалисты"
      extra={<Button type="link" onClick={() => navigate('/specialists')}>Открыть</Button>}
      loading={loading}
    >
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Space orientation="vertical" style={{ width: '100%' }} size="small">
            <Tag bordered={false}>Медики</Tag>
            <Table<SpecialistRow> rowKey="user_id" size="small" pagination={false} dataSource={medics} columns={columns} />
          </Space>
        </Col>
        <Col xs={24} lg={12}>
          <Space orientation="vertical" style={{ width: '100%' }} size="small">
            <Tag bordered={false}>Механики</Tag>
            <Table<SpecialistRow> rowKey="user_id" size="small" pagination={false} dataSource={mechanics} columns={columns} />
          </Space>
        </Col>
      </Row>
    </Card>
  )
}
