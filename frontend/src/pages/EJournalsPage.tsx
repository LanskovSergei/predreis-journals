import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Card, DatePicker, Form, Input, Modal, Radio, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { DownloadOutlined, EyeOutlined, PlusOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import {
  createEJournal,
  deleteEJournal,
  fetchEJournalFile,
  fetchEJournals,
  rejectEJournal,
  signEJournal,
  submitEJournal,
} from '@/api/journals'
import { errorMessage } from '@/api/client'
import type { EJournal, EJournalStatus, Kind } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { OrganizationSelect } from '@/components/CatalogSelects'
import { PageHeader } from '@/components/PageHeader'
import { useOrganizationNames } from '@/components/useOrganizationNames'
import { formatDate, formatDateTime, saveBlob } from '@/utils/labels'

const KIND_LABEL: Record<Kind, string> = { medical: 'Медосмотры', technical: 'Техконтроль' }
const STATUS: Record<EJournalStatus, { label: string; color: string }> = {
  draft: { label: 'Черновик', color: 'default' },
  awaiting_signature: { label: 'Ждёт подписи СА', color: 'gold' },
  signing: { label: 'Подписывается…', color: 'processing' },
  signed: { label: 'Подписан', color: 'success' },
  rejected: { label: 'Отклонён', color: 'error' },
}

/** Электронные журналы: формирует менеджер, подписывает КЭП ПРЕДРЕЙС суперадмин. */
export function EJournalsPage() {
  const { can } = useAuth()
  const { message, modal } = App.useApp()
  const orgNames = useOrganizationNames()
  const [items, setItems] = useState<EJournal[]>([])
  const [loading, setLoading] = useState(true)
  const [kind, setKind] = useState<Kind | undefined>()
  const [status, setStatus] = useState<EJournalStatus | undefined>()
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()

  const buildKinds = (['medical', 'technical'] as Kind[]).filter((k) => can(`${k}:ejournal_build`))
  const canSign = (k: Kind) => can(`${k}:ejournal_sign`)

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true)
      try {
        setItems(await fetchEJournals({ kind, status_filter: status }))
      } catch (err) {
        if (!quiet) message.error(errorMessage(err, 'Не удалось загрузить журналы'))
      } finally {
        if (!quiet) setLoading(false)
      }
    },
    [kind, status, message],
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!items.some((j) => j.status === 'signing')) return
    const timer = window.setInterval(() => void load(true), 5000)
    return () => window.clearInterval(timer)
  }, [items, load])

  const run = async (action: () => Promise<unknown>, done: string) => {
    try {
      await action()
      message.success(done)
      await load(true)
    } catch (err) {
      message.error(errorMessage(err))
    }
  }

  const openFile = async (j: EJournal, what: 'preview' | 'download') => {
    try {
      const { blob, filename } = await fetchEJournalFile(j.id, what)
      if (what === 'preview') window.open(URL.createObjectURL(blob), '_blank', 'noopener')
      else saveBlob(blob, filename)
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось получить файл журнала'))
    }
  }

  const create = async () => {
    const values = await form.validateFields()
    const [from, to] = values.period as [Dayjs, Dayjs]
    setCreating(true)
    try {
      const journal = await createEJournal({
        kind: values.kind,
        organization_id: values.organization_id,
        period_from: from.format('YYYY-MM-DD'),
        period_to: to.format('YYYY-MM-DD'),
      })
      message.success(`Черновик журнала сформирован: записей ${journal.record_count}`)
      setCreateOpen(false)
      form.resetFields()
      await load(true)
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось сформировать журнал'))
    } finally {
      setCreating(false)
    }
  }

  const askSign = (j: EJournal) =>
    modal.confirm({
      title: 'Подписать электронный журнал?',
      content: (
        <Space orientation="vertical">
          <Typography.Text>
            {KIND_LABEL[j.kind]}, {orgNames[j.organization_id] ?? 'организация'}, {formatDate(j.period_from)} —{' '}
            {formatDate(j.period_to)}, записей: {j.record_count}.
          </Typography.Text>
          <Typography.Text type="secondary">
            Журнал подписывается КЭП ООО «ПРЕДРЕЙС». После подписи записи журнала нельзя изменить или удалить.
          </Typography.Text>
        </Space>
      ),
      okText: 'Подписать',
      cancelText: 'Отмена',
      onOk: () => run(() => signEJournal(j.id), 'Журнал отправлен на подпись'),
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
      onOk: () => run(() => rejectEJournal(j.id, reason.trim()), 'Журнал отклонён'),
    })
  }

  const actions = (j: EJournal) => (
    <Space size={4} wrap>
      {j.status === 'draft' && can(`${j.kind}:ejournal_build`) ? (
        <>
          <Button size="small" type="primary" ghost onClick={() => void run(() => submitEJournal(j.id), 'Журнал отправлен на подпись СА')}>
            Отправить на подпись
          </Button>
          <Button size="small" type="text" danger onClick={() => void run(() => deleteEJournal(j.id), 'Черновик удалён')}>
            Удалить
          </Button>
        </>
      ) : null}
      {j.status === 'awaiting_signature' && canSign(j.kind) ? (
        <>
          <Button size="small" type="primary" onClick={() => askSign(j)}>
            Подписать
          </Button>
          <Button size="small" danger onClick={() => askReject(j)}>
            Отклонить
          </Button>
        </>
      ) : null}
      {j.status !== 'draft' && j.status !== 'rejected' ? (
        <Tooltip title="Человекочитаемая версия журнала">
          <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => void openFile(j, 'preview')}>
            PDF
          </Button>
        </Tooltip>
      ) : null}
      {j.status === 'signed' ? (
        <Button size="small" icon={<DownloadOutlined />} onClick={() => void openFile(j, 'download')}>
          ZIP с подписями
        </Button>
      ) : null}
    </Space>
  )

  const columns = useMemo(
    () => [
      { title: 'Журнал', key: 'kind', width: 130, render: (_: unknown, j: EJournal) => KIND_LABEL[j.kind] },
      { title: 'Организация', key: 'org', render: (_: unknown, j: EJournal) => orgNames[j.organization_id] ?? '—' },
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
            {j.status === 'rejected' && j.reject_reason ? (
              <Tooltip title={j.reject_reason}>
                <Typography.Text type="secondary">причина</Typography.Text>
              </Tooltip>
            ) : null}
            {j.sign_error ? (
              <Tooltip title={j.sign_error}>
                <Tag color="error">Подпись не прошла</Tag>
              </Tooltip>
            ) : null}
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
    [orgNames, items],
  )

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="Электронные журналы"
        subtitle="Журнал с подписью ПРЕДРЕЙС за период: формирует менеджер, подписывает суперадмин"
        extra={
          buildKinds.length > 0 ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              Сформировать журнал
            </Button>
          ) : null
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

      <Modal
        title="Сформировать электронный журнал"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void create()}
        okText="Сформировать"
        cancelText="Отмена"
        confirmLoading={creating}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="В журнал попадут подписанные записи за период, которые ещё не вошли в другой журнал."
        />
        <Form form={form} layout="vertical" initialValues={{ kind: buildKinds[0] }}>
          <Form.Item name="kind" label="Журнал" rules={[{ required: true }]}>
            <Radio.Group optionType="button" options={buildKinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
          </Form.Item>
          <Form.Item name="organization_id" label="Организация" rules={[{ required: true, message: 'Выберите организацию' }]}>
            <OrganizationSelect />
          </Form.Item>
          <Form.Item name="period" label="Период" rules={[{ required: true, message: 'Выберите период' }]}>
            <DatePicker.RangePicker format="DD.MM.YYYY" style={{ width: '100%' }} placeholder={['С даты', 'По дату']} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
