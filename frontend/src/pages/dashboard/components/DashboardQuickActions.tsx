import { Button, Card, Col, Row } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { Kind } from '../../../shared/types/api.types'
import { JOURNAL_CONFIG } from '../utils/dashboard.constants'

interface Props {
  kinds: Kind[]
  hasPermission: (permission: string) => boolean
}

export function DashboardQuickActions({ kinds, hasPermission }: Props) {
  const navigate = useNavigate()
  
  const availableKinds = kinds.filter((k) => hasPermission(`${k}:create`))
  
  if (availableKinds.length === 0) return null

  return (
    <Card title="Быстрые действия" size="small">
      <Row gutter={[12, 12]}>
        {availableKinds.map((k) => (
          <Col xs={24} sm={12} lg={6} key={k}>
            <Button block type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/${k}?create=1`)}>
              {JOURNAL_CONFIG[k].add}
            </Button>
          </Col>
        ))}
      </Row>
    </Card>
  )
}
