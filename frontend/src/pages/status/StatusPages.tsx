import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'
import { TokenService } from '../core/auth/token.service'

export function NoAccessPage({ reason }: { reason: string }) {
  return (
    <Result
      status="403"
      title="Журналы недоступны"
      subTitle={reason}
      extra={
        <Button type="primary" onClick={() => TokenService.redirectToPlatform()}>
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
