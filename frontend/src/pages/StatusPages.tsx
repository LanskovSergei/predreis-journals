import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'
import { goToPlatform } from '@/auth/session'

export function NoAccessPage({ reason }: { reason: string }) {
  return (
    <Result
      status="403"
      title="Журналы недоступны"
      subTitle={reason}
      extra={
        <Button type="primary" onClick={() => goToPlatform()}>
          Вернуться в Предрейс
        </Button>
      }
    />
  )
}

export function ComingSoonPage() {
  return (
    <Result
      status="info"
      title="Журналы скоро появятся"
      subTitle="Раздел готовится к запуску. Как только он откроется, он появится в меню ПРЕДРЕЙС."
      extra={
        <Button type="primary" onClick={() => goToPlatform()}>
          Вернуться в Предрейс
        </Button>
      }
    />
  )
}

export function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <Result
      status="404"
      title="Страница не найдена"
      extra={
        <Button type="primary" onClick={() => navigate('/')}>
          На сводку
        </Button>
      }
    />
  )
}

export function JournalNotAvailable() {
  return <Result status="403" title="Этот журнал не ведётся для вашей роли или по договору организации" />
}
