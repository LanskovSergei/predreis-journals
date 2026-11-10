import { Card, Space, Typography, Button } from 'antd'
import { DeleteOutlined, FilePdfOutlined } from '@ant-design/icons'

interface Props {
  selectedCount: number
  canSign: boolean
  canExport: boolean
  canDelete: boolean
  busy: boolean
  onSign: () => void
  onExport: () => void
  onDelete: () => void
  onClearSelection: () => void
}

export function RecordsBatchActions({
  selectedCount,
  canSign,
  canExport,
  canDelete,
  busy,
  onSign,
  onExport,
  onDelete,
  onClearSelection,
}: Props) {
  if (selectedCount === 0) return null

  return (
    <Card size="small">
      <Space wrap>
        <Typography.Text strong>Выбрано: {selectedCount}</Typography.Text>
        {canSign && (
          <Button type="primary" loading={busy} onClick={onSign} disabled={selectedCount > 50}>
            Подписать
          </Button>
        )}
        {canExport && (
          <Button icon={<FilePdfOutlined />} loading={busy} onClick={onExport}>
            Выгрузить PDF
          </Button>
        )}
        {canDelete && (
          <Button danger icon={<DeleteOutlined />} onClick={onDelete}>
            Удалить
          </Button>
        )}
        <Button type="text" onClick={onClearSelection}>
          Снять выбор
        </Button>
        {selectedCount > 50 && (
          <Typography.Text type="warning">За раз можно подписать до 50 записей</Typography.Text>
        )}
      </Space>
    </Card>
  )
}
