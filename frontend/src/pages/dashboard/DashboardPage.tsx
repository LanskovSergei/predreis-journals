import { Space } from 'antd'
import { useAuth } from '../../core/auth/useAuth'
import { PageHeader } from '../../shared/components/PageHeader'
import type { Kind } from '../../shared/types/api.types'
import { useDashboardData } from './hooks/useDashboardData'
import { DashboardCertificateAlert } from './components/DashboardCertificateAlert'
import { DashboardQuickActions } from './components/DashboardQuickActions'
import { DashboardJournalsStats } from './components/DashboardJournalsStats'
import { DashboardCatalogStats } from './components/DashboardCatalogStats'

export function DashboardPage() {
  const { user, hasPermission, hasJournalAccess } = useAuth()
  
  const isSpecialist = user?.role === 'medic' || user?.role === 'mechanic'
  const kinds = (['medical', 'technical'] as Kind[]).filter(hasJournalAccess)
  
  const { stats, cert, loading } = useDashboardData(isSpecialist)

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader 
        title="Электронные журналы" 
        subtitle="Медосмотры и техконтроль: записи, подписи и выгрузки" 
      />

      {isSpecialist && <DashboardCertificateAlert cert={cert} />}

      <DashboardQuickActions kinds={kinds} hasPermission={hasPermission} />

      <DashboardJournalsStats kinds={kinds} stats={stats} loading={loading} />

      <DashboardCatalogStats stats={stats} loading={loading} />
    </Space>
  )
}
