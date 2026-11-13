import { Button, Card, Space, Typography } from 'antd'
import { FileSearchOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { Kind } from '../../../shared/types/api.types'

const COPY: Record<Kind, { createHint: string; archive: string }> = {
  medical: {
    createHint: 'Внести данные о медицинском осмотре',
    archive: 'Медосмотры',
  },
  technical: {
    createHint: 'Внести данные техконтроля',
    archive: 'Техконтроль',
  },
}

export function DashboardSpecialistActions({ kinds }: { kinds: Kind[] }) {
  const navigate = useNavigate()
  const kind = kinds[0]
  if (!kind) return null
  const copy = COPY[kind]

  return (
    <Card title="Быстрые действия" size="small">
      <Space wrap size="middle">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/${kind}?create=1`)}>
          Создать запись
          <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, fontWeight: 400, color: 'inherit', opacity: 0.85 }}>
            {copy.createHint}
          </Typography.Text>
        </Button>
        <Button icon={<FileSearchOutlined />} onClick={() => navigate(`/${kind}`)}>
          Архив записей
          <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, fontWeight: 400 }}>
            Поиск, проверка и подпись записей
          </Typography.Text>
        </Button>
      </Space>
    </Card>
  )
}
