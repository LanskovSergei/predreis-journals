import { Button, Card, Col, Row, Space, Statistic } from 'antd'
import { useNavigate } from 'react-router-dom'
import type { Kind, RecordCounters, Stats } from '../../../shared/types/api.types'
import { JOURNAL_CONFIG } from '../utils/dashboard.constants'

interface Props {
  kinds: Kind[]
  stats: Stats | null
  loading: boolean
}

export function DashboardJournalsStats({ kinds, stats, loading }: Props) {
  const navigate = useNavigate()

  const getCounters = (kind: Kind): RecordCounters | null | undefined => stats?.[kind]

  return (
    <Row gutter={[16, 16]}>
      {kinds.map((k) => (
        <Col xs={24} lg={12} key={k}>
          <Card
            title={
              <Space>
                {JOURNAL_CONFIG[k].icon}
                {JOURNAL_CONFIG[k].title}
              </Space>
            }
            extra={<Button type="link" onClick={() => navigate(`/${k}`)}>Открыть архив</Button>}
            loading={loading}
          >
            <Row gutter={16}>
              <Col span={8}>
                <Card size="small" hoverable onClick={() => navigate(`/${k}?signed=0`)}>
                  <Statistic title="На подпись" value={getCounters(k)?.to_sign ?? 0} />
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" hoverable onClick={() => navigate(`/${k}?signed=1`)}>
                  <Statistic title="Подписано" value={getCounters(k)?.signed ?? 0} />
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" hoverable onClick={() => navigate(`/${k}`)}>
                  <Statistic title="Всего" value={getCounters(k)?.total ?? 0} />
                </Card>
              </Col>
            </Row>
          </Card>
        </Col>
      ))}
    </Row>
  )
}
