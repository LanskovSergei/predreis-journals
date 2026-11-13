import { Card, Space, Tabs } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../core/auth/useAuth'
import { PageHeader } from '../../shared/components/PageHeader'
import { OrganizationsTab } from './components/OrganizationsTab'
import { PeopleAndVehiclesTab } from './components/PeopleAndVehiclesTab'

const CATALOG_SUBTITLE =
  'Картотека клиентов ПРЕДРЕЙС: организации на ЭПЛ (добавляются с платформы автоматически) и бумажных путевых листах (добавляются вручную). Если компания переходит на ЭПЛ, карточки автоматически синхронизируются, когда клиент регистрируется на платформе.'

export function CatalogPage() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission('catalog:manage')
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'orgs'
  const create = params.get('create')

  const setTab = (key: string) => {
    const next = new URLSearchParams(params)
    next.set('tab', key)
    next.delete('create')
    setParams(next, { replace: true })
  }

  const clearCreate = () => {
    if (!params.get('create')) return
    const next = new URLSearchParams(params)
    next.delete('create')
    setParams(next, { replace: true })
  }

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <PageHeader title="Каталог" subtitle={CATALOG_SUBTITLE} />
      <Card>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'orgs',
              label: 'Организации',
              children: (
                <OrganizationsTab
                  canManage={canManage}
                  startCreate={create === 'org'}
                  onCreateConsumed={clearCreate}
                />
              ),
            },
            {
              key: 'drivers',
              label: 'Водители',
              children: (
                <PeopleAndVehiclesTab
                  kind="drivers"
                  canManage={canManage}
                  startCreate={tab === 'drivers' && create === '1'}
                  onCreateConsumed={clearCreate}
                />
              ),
            },
            {
              key: 'vehicles',
              label: 'Транспортные средства',
              children: (
                <PeopleAndVehiclesTab
                  kind="vehicles"
                  canManage={canManage}
                  startCreate={tab === 'vehicles' && create === '1'}
                  onCreateConsumed={clearCreate}
                />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
