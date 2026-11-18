import { Card, Space, Typography, Button } from 'antd'
import { DeleteOutlined, FilePdfOutlined, FileZipOutlined } from '@ant-design/icons'

interface Props {
  selectedCount: number
  /** Сколько из отмеченных можно подписать (0 — кнопки нет). */
  signableCount: number
  documentCount: number
  canExport: boolean
  /** Сколько из отмеченных можно удалить: только неподписанные (0 — кнопки нет). */
  deletableCount: number
  busy: boolean
  onSign: () => void
  onExport: () => void
  onDownloadDocuments: () => void
  onDelete: () => void
  onClearSelection: () => void
}

export function RecordsBatchActions({
  selectedCount,
  signableCount,
  documentCount,
  canExport,
  deletableCount,
  busy,
  onSign,
  onExport,
  onDownloadDocuments,
  onDelete,
  onClearSelection,
}: Props) {
  if (selectedCount === 0) return null

  return (
    <Card size="small">
      <Space wrap>
        <Typography.Text strong>Выбрано: {selectedCount}</Typography.Text>
        {signableCount > 0 && (
          <Button type="primary" loading={busy} onClick={onSign} disabled={signableCount > 50}>
            Подписать{signableCount < selectedCount ? ` (${signableCount})` : ''}
          </Button>
        )}
        {canExport && (
          <Button icon={<FilePdfOutlined />} loading={busy} onClick={onExport}>
            Выгрузить PDF
          </Button>
        )}
        {documentCount > 0 && (
          <Button icon={<FileZipOutlined />} loading={busy} onClick={onDownloadDocuments}>
            Скачать документы
          </Button>
        )}
        {deletableCount > 0 && (
          <Button danger icon={<DeleteOutlined />} onClick={onDelete}>
            Удалить{deletableCount < selectedCount ? ` (${deletableCount})` : ''}
          </Button>
        )}
        <Button type="text" onClick={onClearSelection}>
          Снять выбор
        </Button>
        {signableCount > 50 && (
          <Typography.Text type="warning">За раз можно подписать до 50 записей</Typography.Text>
        )}
      </Space>
    </Card>
  )
}
