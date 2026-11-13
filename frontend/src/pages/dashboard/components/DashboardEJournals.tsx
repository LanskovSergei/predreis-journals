import { Button, Card, Col, Row, Statistic } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { JournalsService } from '../../../core/api/journals.service'
import type { EJournal } from '../../../shared/types/api.types'

export function DashboardEJournals() {
  const navigate = useNavigate()
  const [items, setItems] = useState<EJournal[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    JournalsService.getEJournals({})
      .then((data) => {
        if (!cancelled) setItems(data)
      })
      .catch(() => {
        if (!cancelled) setItems([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const awaiting = items.filter((j) => j.status === 'awaiting_signature' || j.status === 'signing').length
  const signed = items.filter((j) => j.status === 'signed').length

  return (
    <Card
      title="Электронные документы"
      extra={<Button type="link" onClick={() => navigate('/ejournals')}>Открыть</Button>}
      loading={loading}
    >
      <Row gutter={16}>
        <Col span={8}>
          <Statistic title="Всего журналов" value={items.length} />
        </Col>
        <Col span={8}>
          <Statistic title="Ждут подписи" value={awaiting} />
        </Col>
        <Col span={8}>
          <Statistic title="Подписаны" value={signed} />
        </Col>
      </Row>
    </Card>
  )
}
