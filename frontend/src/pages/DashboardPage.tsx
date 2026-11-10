import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Col, Row, Space, Statistic, Tag } from 'antd'
import { MedicineBoxOutlined, PlusOutlined, ToolOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { fetchMyCertificates, fetchStats } from '@/api/journals'
import { errorMessage } from '@/api/client'
import type { Kind, MyCertificates, RecordCounters, Stats } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { PageHeader } from '@/components/PageHeader'
import { formatDate } from '@/utils/labels'

const JOURNAL = {
  medical: { title: 'Медосмотры', icon: <MedicineBoxOutlined />, add: 'Добавить медосмотр' },
  technical: { title: 'Техконтроль', icon: <ToolOutlined />, add: 'Добавить техконтроль' },
} as const

/** Сводка: счётчики записей по журналам, для специалиста — его сертификат, для менеджера — справочники. */
export function DashboardPage() {
  const { me, can, hasJournal } = useAuth()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [cert, setCert] = useState<MyCertificates | null>(null)
  const [loading, setLoading] = useState(true)
  const isSpecialist = me?.role === 'medic' || me?.role === 'mechanic'
  const kinds = (['medical', 'technical'] as Kind[]).filter(hasJournal)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [s, c] = await Promise.all([
          fetchStats(),
          isSpecialist ? fetchMyCertificates().catch(() => null) : Promise.resolve(null),
        ])
        if (!cancelled) {
          setStats(s)
          setCert(c)
        }
      } catch (err) {
        if (!cancelled) message.error(errorMessage(err, 'Не удалось загрузить сводку'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [isSpecialist, message])

  const counters = (kind: Kind): RecordCounters | null | undefined => stats?.[kind]

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader title="Электронные журналы" subtitle="Медосмотры и техконтроль: записи, подписи и выгрузки" />

      {isSpecialist && cert ? (
        cert.status === 'active' ? (
          <Alert
            type="success"
            showIcon
            title={`Сертификат для подписи действует до ${formatDate(cert.valid_to)}`}
          />
        ) : (
          <Alert
            type="warning"
            showIcon
            title={cert.status === 'expired' ? 'Срок сертификата для подписи истёк' : 'Нет действующего сертификата для подписи'}
            description="Подписать записи не получится. Обратитесь к администратору платформы."
          />
        )
      ) : null}

      {kinds.some((k) => can(`${k}:create`)) ? (
        <Card title="Быстрые действия" size="small">
          <Row gutter={[12, 12]}>
            {kinds
              .filter((k) => can(`${k}:create`))
              .map((k) => (
                <Col xs={24} sm={12} lg={6} key={k}>
                  <Button block type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/${k}?create=1`)}>
                    {JOURNAL[k].add}
                  </Button>
                </Col>
              ))}
          </Row>
        </Card>
      ) : null}

      <Row gutter={[16, 16]}>
        {kinds.map((k) => (
          <Col xs={24} lg={12} key={k}>
            <Card
              title={
                <Space>
                  {JOURNAL[k].icon}
                  {JOURNAL[k].title}
                </Space>
              }
              extra={<Button type="link" onClick={() => navigate(`/${k}`)}>Открыть архив</Button>}
              loading={loading}
            >
              <Row gutter={16}>
                <Col span={8}>
                  <Card size="small" hoverable onClick={() => navigate(`/${k}?signed=0`)}>
                    <Statistic title="На подпись" value={counters(k)?.to_sign ?? 0} />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" hoverable onClick={() => navigate(`/${k}?signed=1`)}>
                    <Statistic title="Подписано" value={counters(k)?.signed ?? 0} />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" hoverable onClick={() => navigate(`/${k}`)}>
                    <Statistic title="Всего" value={counters(k)?.total ?? 0} />
                  </Card>
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>

      {stats?.organizations || stats?.drivers ? (
        <Row gutter={[16, 16]}>
          {stats.organizations ? (
            <Col xs={24} sm={12} lg={6}>
              <Card loading={loading}>
                <Statistic
                  title="Организации"
                  value={stats.organizations.active}
                  suffix={<Tag bordered={false}>из {stats.organizations.total}</Tag>}
                />
              </Card>
            </Col>
          ) : null}
          {stats.drivers ? (
            <Col xs={24} sm={12} lg={6}>
              <Card loading={loading}>
                <Statistic
                  title="Водители"
                  value={stats.drivers.active}
                  suffix={<Tag bordered={false}>из {stats.drivers.total}</Tag>}
                />
              </Card>
            </Col>
          ) : null}
        </Row>
      ) : null}
    </Space>
  )
}
