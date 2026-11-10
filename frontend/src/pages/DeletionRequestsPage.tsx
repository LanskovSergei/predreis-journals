import { useCallback, useEffect, useState } from 'react'
import { App, Button, Card, Descriptions, Drawer, Input, Segmented, Space, Table, Tag, Typography } from 'antd'
import { fetchDeletionRequests, fetchRecord, resolveDeletionRequest } from '@/api/journals'
import { errorMessage } from '@/api/client'
import type { AnyRecord, DeletionRequest, DeletionStatus, MedicalRecord, TechnicalRecord } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { formatDateTime, phaseLabels, resultLabels } from '@/utils/labels'

const KIND_LABEL = { medical: 'Медосмотр', technical: 'Техконтроль' } as const

/** Запросы на удаление подписанных записей: решение принимает Админ или Суперадмин. */
export function DeletionRequestsPage() {
  const { message, modal } = App.useApp()
  const [status, setStatus] = useState<DeletionStatus>('pending')
  const [items, setItems] = useState<DeletionRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [viewing, setViewing] = useState<{ request: DeletionRequest; record: AnyRecord | null } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await fetchDeletionRequests(status))
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось загрузить запросы'))
    } finally {
      setLoading(false)
    }
  }, [status, message])

  useEffect(() => {
    void load()
  }, [load])

  const open = async (request: DeletionRequest) => {
    setViewing({ request, record: null })
    try {
      setViewing({ request, record: await fetchRecord(request.record_kind, request.record_id) })
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось открыть запись'))
    }
  }

  const decide = (request: DeletionRequest, decision: 'approve' | 'reject') => {
    let comment = ''
    modal.confirm({
      title: decision === 'approve' ? 'Удалить подписанную запись?' : 'Отклонить запрос?',
      content: (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            {decision === 'approve'
              ? 'Запись будет удалена из журнала. Действие нельзя отменить, оно сохраняется в журнале аудита.'
              : 'Запись останется в журнале без изменений.'}
          </Typography.Text>
          <Input.TextArea rows={3} placeholder="Комментарий (необязательно)" onChange={(e) => (comment = e.target.value)} />
        </Space>
      ),
      okText: decision === 'approve' ? 'Удалить запись' : 'Отклонить запрос',
      okButtonProps: { danger: decision === 'approve' },
      cancelText: 'Отмена',
      onOk: async () => {
        try {
          await resolveDeletionRequest(request.id, decision, comment.trim())
          message.success(decision === 'approve' ? 'Запись удалена' : 'Запрос отклонён')
          setViewing(null)
          await load()
        } catch (err) {
          message.error(errorMessage(err))
        }
      },
    })
  }

  const record = viewing?.record
  const medical = record as MedicalRecord | null
  const technical = record as TechnicalRecord | null

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="Запросы на удаление"
        subtitle="Удаление подписанной записи — повод для внутренней проверки. Решение принимает Админ или Суперадмин."
      />
      <Segmented<DeletionStatus>
        value={status}
        onChange={setStatus}
        options={[
          { value: 'pending', label: 'Ждут решения' },
          { value: 'approved', label: 'Удалены' },
          { value: 'rejected', label: 'Отклонены' },
        ]}
      />
      <Card styles={{ body: { padding: 0 } }}>
        <Table<DeletionRequest>
          rowKey="id"
          loading={loading}
          dataSource={items}
          scroll={{ x: 800 }}
          pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (t) => `Всего: ${t}` }}
          locale={{ emptyText: status === 'pending' ? 'Запросов, ждущих решения, нет' : 'Запросов нет' }}
          columns={[
            { title: 'Запрошено', dataIndex: 'created_at', width: 150, render: (v: string) => formatDateTime(v) },
            { title: 'Журнал', dataIndex: 'record_kind', width: 130, render: (v: DeletionRequest['record_kind']) => KIND_LABEL[v] },
            { title: 'Причина', dataIndex: 'reason', render: (v: string | null) => v || <Typography.Text type="secondary">не указана</Typography.Text> },
            ...(status === 'pending'
              ? []
              : [{ title: 'Комментарий к решению', dataIndex: 'resolution_comment', render: (v: string | null) => v || '—' }]),
            {
              title: '',
              key: 'actions',
              width: 300,
              render: (_: unknown, r: DeletionRequest) => (
                <Space size={4} wrap>
                  <Button size="small" type="link" onClick={() => void open(r)}>
                    Открыть запись
                  </Button>
                  {r.status === 'pending' ? (
                    <>
                      <Button size="small" danger onClick={() => decide(r, 'approve')}>
                        Удалить запись
                      </Button>
                      <Button size="small" onClick={() => decide(r, 'reject')}>
                        Отклонить
                      </Button>
                    </>
                  ) : (
                    <Tag color={r.status === 'approved' ? 'error' : 'default'}>
                      {r.status === 'approved' ? 'Удалена' : 'Отклонён'} {formatDateTime(r.resolved_at)}
                    </Tag>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Drawer title="Запись из запроса" open={Boolean(viewing)} onClose={() => setViewing(null)} size="default">
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
    </Space>
  )
}
