import { Button, Card, Col, Row, Space, Statistic } from 'antd'
import { CarOutlined, DatabaseOutlined, PlusOutlined, UserAddOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { Stats } from '../../../shared/types/api.types'

interface Props {
  stats: Stats | null
  loading: boolean
  canManage: boolean
}

export function DashboardOrganizations({ stats, loading, canManage }: Props) {
  const navigate = useNavigate()
  const orgs = stats?.organizations
  const drivers = stats?.drivers
  if (!orgs && !drivers) return null

  return (
    <Card title="Организации" loading={loading}>
      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}>
          <Statistic title="На бумажных путевых листах" value={orgs?.paper ?? 0} />
        </Col>
        <Col xs={12} lg={6}>
          <Statistic title="На ЭПЛ" value={orgs?.epl ?? 0} />
        </Col>
        <Col xs={12} lg={6}>
          <Statistic title="Всего организаций" value={orgs?.total ?? 0} />
        </Col>
        <Col xs={12} lg={6}>
          <Statistic title="Всего водителей" value={drivers?.total ?? 0} />
        </Col>
      </Row>
      <Space wrap style={{ marginTop: 16 }}>
        <Button icon={<DatabaseOutlined />} onClick={() => navigate('/catalog')}>
          Каталог организаций
        </Button>
        {canManage && (
          <>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/catalog?tab=orgs&create=org')}>
              Добавить новую организацию
            </Button>
            <Button icon={<UserAddOutlined />} onClick={() => navigate('/catalog?tab=drivers&create=1')}>
              Добавить водителя
            </Button>
            <Button icon={<CarOutlined />} onClick={() => navigate('/catalog?tab=vehicles&create=1')}>
              Добавить авто
            </Button>
          </>
        )}
      </Space>
    </Card>
  )
}
