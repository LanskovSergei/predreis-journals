import { App, Button, Card, Input, Segmented, Space, Table, Tag, Typography } from 'antd'
import type { DeletionRequest, DeletionStatus } from '../../shared/types/api.types'
import { PageHeader } from '../../shared/components/PageHeader'
import { formatDateTime } from '../../shared/utils/labels'
import { useDeletionRequests } from './hooks/useDeletionRequests'
import { DeletionRequestDrawer } from './components/DeletionRequestDrawer'

const KIND_LABEL = { medical: 'Медосмотр', technical: 'Техконтроль' } as const

export function DeletionRequestsPage() {
  const { modal } = App.useApp()
  const {
    status, setStatus,
    items, loading,
    viewing, setViewing,
    openRecord, decide
  } = useDeletionRequests()

  const handleDecide = (request: DeletionRequest, decision: 'approve' | 'reject') => {
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
      onOk: decide(request, decision, comment),
    })
  }

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
                  <Button size="small" type="link" onClick={() => void openRecord(r)}>
                    Открыть запись
                  </Button>
                  {r.status === 'pending' ? (
                    <>
                      <Button size="small" danger onClick={() => handleDecide(r, 'approve')}>
                        Удалить запись
                      </Button>
                      <Button size="small" onClick={() => handleDecide(r, 'reject')}>
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

      <DeletionRequestDrawer viewing={viewing} onClose={() => setViewing(null)} />
    </Space>
  )
}
