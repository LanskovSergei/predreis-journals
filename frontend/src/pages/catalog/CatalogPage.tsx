import { Card, Space, Tabs } from 'antd'
import { useAuth } from '../../core/auth/useAuth'
import { PageHeader } from '../../shared/components/PageHeader'
import { OrganizationsTab } from './components/OrganizationsTab'
import { PeopleAndVehiclesTab } from './components/PeopleAndVehiclesTab'

/** Общий каталог: организации из ПРЕДРЕЙС и добавленные вручную, их водители и ТС. */
export function CatalogPage() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission('catalog:manage')
  
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader
        title="Каталог"
        subtitle="Организации из ПРЕДРЕЙС и бумажные клиенты, добавленные вручную. Карточки объединяются автоматически, когда клиент регистрируется на платформе."
      />
      <Card>
        <Tabs
          items={[
            { key: 'orgs', label: 'Организации', children: <OrganizationsTab canManage={canManage} /> },
            { key: 'drivers', label: 'Водители', children: <PeopleAndVehiclesTab kind="drivers" canManage={canManage} /> },
            { key: 'vehicles', label: 'Транспортные средства', children: <PeopleAndVehiclesTab kind="vehicles" canManage={canManage} /> },
          ]}
        />
      </Card>
    </Space>
  )
}
