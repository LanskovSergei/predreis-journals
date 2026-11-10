import { Alert } from 'antd'
import type { MyCertificates } from '../../../shared/types/api.types'
import { formatDate } from '../../../shared/utils/labels'

interface Props {
  cert: MyCertificates | null
}

export function DashboardCertificateAlert({ cert }: Props) {
  if (!cert) return null

  if (cert.status === 'active') {
    return (
      <Alert
        type="success"
        showIcon
        title={`Сертификат для подписи действует до ${formatDate(cert.valid_to)}`}
      />
    )
  }

  return (
    <Alert
      type="warning"
      showIcon
      title={cert.status === 'expired' ? 'Срок сертификата для подписи истёк' : 'Нет действующего сертификата для подписи'}
      description="Подписать записи не получится. Обратитесь к администратору платформы."
    />
  )
}
