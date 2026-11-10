import { useMemo } from 'react'
import { App, Button, Card, Input, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, EyeOutlined, PlusOutlined } from '@ant-design/icons'
import { JournalsService } from '../../core/api/journals.service'
import type { EJournal, EJournalStatus, Kind } from '../../shared/types/api.types'
import { useAuth } from '../../core/auth/useAuth'
import { PageHeader } from '../../shared/components/PageHeader'
import { formatDate, formatDateTime } from '../../shared/utils/labels'
import { useEJournals } from './hooks/useEJournals'
import { CreateEJournalModal } from './components/CreateEJournalModal'

export const KIND_LABEL: Record<Kind, string> = { medical: 'Медосмотры', technical: 'Техконтроль' }
const STATUS: Record<EJournalStatus, { label: string; color: string }> = {
  draft: { label: 'Черновик', color: 'default' },
  awaiting_signature: { label: 'Ждёт подписи СА', color: 'gold' },
  signing: { label: 'Подписывается…', color: 'processing' },
  signed: { label: 'Подписан', color: 'success' },
  rejected: { label: 'Отклонён', color: 'error' },
}

export function EJournalsPage() {
  const { hasPermission } = useAuth()
  const { modal } = App.useApp()
  const {
    items, loading,
    kind, setKind,
    status, setStatus,
    createOpen, setCreateOpen,
    creating, create,
    runAction, openFile
  } = useEJournals()

  const buildKinds = (['medical', 'technical'] as Kind[]).filter((k) => hasPermission(`${k}:ejournal_build`))
  const canSign = (k: Kind) => hasPermission(`${k}:ejournal_sign`)

  const askSign = (j: EJournal) =>
    modal.confirm({
      title: 'Подписать электронный журнал?',
      content: (
        <Space orientation="vertical">
          <Typography.Text>
            {KIND_LABEL[j.kind]}, {formatDate(j.period_from)} —{' '}
            {formatDate(j.period_to)}, записей: {j.record_count}.
          </Typography.Text>
          <Typography.Text type="secondary">
            Журнал подписывается КЭП ООО «ПРЕДРЕЙС». После подписи записи журнала нельзя изменить или удалить.
          </Typography.Text>
        </Space>
      ),
      okText: 'Подписать',
      cancelText: 'Отмена',
      onOk: () => runAction(() => JournalsService.signEJournal(j.id), 'Журнал отправлен на подпись'),
    })

  const askReject = (j: EJournal) => {
    let reason = ''
    modal.confirm({
      title: 'Отклонить журнал?',
      content: (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <Typography.Text type="secondary">Журнал расформируется, записи снова станут обычными подписанными.</Typography.Text>
          <Input.TextArea rows={3} placeholder="Причина" onChange={(e) => (reason = e.target.value)} />
        </Space>
      ),
      okText: 'Отклонить',
      okButtonProps: { danger: true },
      cancelText: 'Отмена',
      onOk: () => runAction(() => JournalsService.rejectEJournal(j.id, reason.trim()), 'Журнал отклонён'),
    })
  }

  const actions = (j: EJournal) => (
    <Space size={4} wrap>
      {j.status === 'draft' && hasPermission(`${j.kind}:ejournal_build`) && (
        <>
          <Button size="small" type="primary" ghost onClick={() => void runAction(() => JournalsService.submitEJournal(j.id), 'Журнал отправлен на подпись СА')}>
            Отправить на подпись
          </Button>
          <Button size="small" type="text" danger onClick={() => void runAction(() => JournalsService.deleteEJournal(j.id), 'Черновик удалён')}>
            Удалить
          </Button>
        </>
      )}
      {j.status === 'awaiting_signature' && canSign(j.kind) && (
        <>
          <Button size="small" type="primary" onClick={() => askSign(j)}>
            Подписать
          </Button>
          <Button size="small" danger onClick={() => askReject(j)}>
            Отклонить
          </Button>
        </>
      )}
      {j.status !== 'draft' && j.status !== 'rejected' && (
        <Tooltip title="Человекочитаемая версия журнала">
          <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => void openFile(j, 'preview')}>
            PDF
          </Button>
        </Tooltip>
      )}
      {j.status === 'signed' && (
        <Button size="small" icon={<DownloadOutlined />} onClick={() => void openFile(j, 'download')}>
          ZIP с подписями
        </Button>
      )}
    </Space>
  )

  const columns = useMemo(
    () => [
      { title: 'Журнал', key: 'kind', width: 130, render: (_: unknown, j: EJournal) => KIND_LABEL[j.kind] },
      {
        title: 'Период',
        key: 'period',
        width: 200,
        render: (_: unknown, j: EJournal) => `${formatDate(j.period_from)} — ${formatDate(j.period_to)}`,
      },
      { title: 'Записей', dataIndex: 'record_count', width: 90 },
      {
        title: 'Статус',
        key: 'status',
        width: 190,
        render: (_: unknown, j: EJournal) => (
          <Space size={4} wrap>
            <Tag color={STATUS[j.status].color}>{STATUS[j.status].label}</Tag>
            {j.status === 'rejected' && j.reject_reason && (
              <Tooltip title={j.reject_reason}>
                <Typography.Text type="secondary">причина</Typography.Text>
              </Tooltip>
            )}
            {j.sign_error && (
              <Tooltip title={j.sign_error}>
                <Tag color="error">Подпись не прошла</Tag>
              </Tooltip>
            )}
          </Space>
        ),
      },
      {
        title: 'Подписан',
        key: 'signed_at',
        width: 140,
        render: (_: unknown, j: EJournal) => (j.signed_at ? formatDateTime(j.signed_at) : '—'),
      },
      { title: '', key: 'actions', render: (_: unknown, j: EJournal) => actions(j) },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items],
  )

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="Электронные журналы"
        subtitle="Журнал с подписью ПРЕДРЕЙС за период: формирует менеджер, подписывает суперадмин"
        extra={
          buildKinds.length > 0 && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              Сформировать журнал
            </Button>
          )
        }
      />
      <Card>
        <Space wrap className="filterBar">
          <Select allowClear placeholder="Журнал" value={kind} onChange={setKind}
            options={[{ value: 'medical', label: 'Медосмотры' }, { value: 'technical', label: 'Техконтроль' }]} />
          <Select allowClear placeholder="Статус" value={status} onChange={setStatus}
            options={(Object.keys(STATUS) as EJournalStatus[]).map((s) => ({ value: s, label: STATUS[s].label }))} />
        </Space>
      </Card>
      <Card styles={{ body: { padding: 0 } }}>
        <Table<EJournal>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          scroll={{ x: 1000 }}
          pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (t) => `Всего: ${t}` }}
          locale={{ emptyText: buildKinds.length ? 'Журналов нет. Сформируйте журнал за период кнопкой «Сформировать журнал».' : 'Журналов нет' }}
        />
      </Card>

      <CreateEJournalModal
        open={createOpen}
        creating={creating}
        buildKinds={buildKinds}
        onClose={() => setCreateOpen(false)}
        onCreate={create}
      />
    </Space>
  )
}
