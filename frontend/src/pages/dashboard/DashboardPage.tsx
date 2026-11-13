import { Space } from 'antd'
import { useAuth } from '../../core/auth/useAuth'
import { PageHeader } from '../../shared/components/PageHeader'
import type { Kind } from '../../shared/types/api.types'
import { useDashboardData } from './hooks/useDashboardData'
import { DashboardCertificateAlert } from './components/DashboardCertificateAlert'
import { DashboardSpecialistActions } from './components/DashboardSpecialistActions'
import { DashboardOrganizations } from './components/DashboardOrganizations'
import { DashboardJournalsStats } from './components/DashboardJournalsStats'
import { DashboardEJournals } from './components/DashboardEJournals'
import { DashboardSpecialists } from './components/DashboardSpecialists'

export function DashboardPage() {
  const { user, hasPermission, hasJournalAccess } = useAuth()

  const isSpecialist = user?.role === 'medic' || user?.role === 'mechanic'
  const isManager = hasPermission('catalog:view')
  const isSA = user?.role === 'superadmin'
  const kinds = (['medical', 'technical'] as Kind[]).filter(hasJournalAccess)
  const canCreate = (k: Kind) => hasPermission(`${k}:create`)

  const { stats, cert, loading } = useDashboardData(isSpecialist)

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="Электронные журналы"
        subtitle="Медосмотры и техконтроль: записи, подписи и выгрузки"
      />

      {isSpecialist && <DashboardCertificateAlert cert={cert} />}
      {isSpecialist && <DashboardSpecialistActions kinds={kinds} />}
      {isManager && (
        <DashboardOrganizations
          stats={stats}
          loading={loading}
          canManage={hasPermission('catalog:manage')}
        />
      )}

      <DashboardJournalsStats kinds={kinds} stats={stats} loading={loading} canCreate={canCreate} />

      {isSA && <DashboardEJournals />}
      {isSA && <DashboardSpecialists />}
    </Space>
  )
}
