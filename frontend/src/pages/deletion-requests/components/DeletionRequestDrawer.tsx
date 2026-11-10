import { Descriptions, Drawer, Typography } from 'antd'
import type { AnyRecord, DeletionRequest, MedicalRecord, TechnicalRecord } from '../../../shared/types/api.types'
import { formatDateTime, phaseLabels, resultLabels } from '../../../shared/utils/labels'

interface Props {
  viewing: { request: DeletionRequest; record: AnyRecord | null } | null
  onClose: () => void
}

export function DeletionRequestDrawer({ viewing, onClose }: Props) {
  const record = viewing?.record
  const medical = record as MedicalRecord | null
  const technical = record as TechnicalRecord | null

  return (
    <Drawer title="Запись из запроса" open={Boolean(viewing)} onClose={onClose} size="default">
      {viewing && record ? (
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="Дата и время">{formatDateTime(record.performed_at)}</Descriptions.Item>
          <Descriptions.Item label="Организация">
            {record.snapshot?.organization?.short_name || record.snapshot?.organization?.name || '—'}
          </Descriptions.Item>
          {viewing.request.record_kind === 'medical' ? (
            <>
              <Descriptions.Item label="Водитель">{record.snapshot?.driver?.full_name ?? '—'}</Descriptions.Item>
              <Descriptions.Item label="Осмотр">{medical?.phase ? phaseLabels[medical.phase] : '—'}</Descriptions.Item>
            </>
          ) : (
            <>
              <Descriptions.Item label="ТС">
                {`${record.snapshot?.vehicle?.brand ?? ''} ${record.snapshot?.vehicle?.model ?? ''}, ${record.snapshot?.vehicle?.plate ?? ''}`}
              </Descriptions.Item>
              <Descriptions.Item label="Одометр">{technical?.odometer ?? '—'}</Descriptions.Item>
            </>
          )}
          <Descriptions.Item label="Результат">{resultLabels[record.result]}</Descriptions.Item>
          <Descriptions.Item label="Специалист">{record.snapshot?.specialist?.full_name ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="Причина запроса">{viewing.request.reason || 'не указана'}</Descriptions.Item>
        </Descriptions>
      ) : (
        <Typography.Text type="secondary">Загрузка…</Typography.Text>
      )}
    </Drawer>
  )
}
