import { Card, Col, Row, Statistic, Tag } from 'antd'
import type { Stats } from '../../../shared/types/api.types'

interface Props {
  stats: Stats | null
  loading: boolean
}

export function DashboardCatalogStats({ stats, loading }: Props) {
  if (!stats?.organizations && !stats?.drivers) {
    return null
  }

  return (
    <Row gutter={[16, 16]}>
      {stats.organizations && (
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic
              title="Организации"
              value={stats.organizations.active}
              suffix={<Tag bordered={false}>из {stats.organizations.total}</Tag>}
            />
          </Card>
        </Col>
      )}
      {stats.drivers && (
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic
              title="Водители"
              value={stats.drivers.active}
              suffix={<Tag bordered={false}>из {stats.drivers.total}</Tag>}
            />
          </Card>
        </Col>
      )}
    </Row>
  )
}
