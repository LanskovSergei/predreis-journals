import { App as AntApp, ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/auth/AuthContext'
import { DEV_LOGIN } from '@/auth/session'
import { PageLoader } from '@/components/PageLoader'
import { AppLayout } from '@/layout/AppLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { DevLoginPage } from '@/pages/DevLoginPage'
import { RecordsPage } from '@/pages/RecordsPage'
import { EJournalsPage } from '@/pages/EJournalsPage'
import { DeletionRequestsPage } from '@/pages/DeletionRequestsPage'
import { CatalogPage } from '@/pages/CatalogPage'
import { SpecialistsPage } from '@/pages/SpecialistsPage'
import type { ReactNode } from 'react'
import { JournalNotAvailable, NoAccessPage, NotFoundPage } from '@/pages/StatusPages'
import type { Kind } from '@/api/types'
import { antdTheme } from '@/theme/antdTheme'
import '@/styles/global.css'

function Journal({ kind }: { kind: Kind }) {
  const { hasJournal } = useAuth()
  return hasJournal(kind) ? <RecordsPage key={kind} kind={kind} /> : <JournalNotAvailable />
}

/** Раздел только для ролей с нужным правом (меню его и так не показывает, это защита прямой ссылки). */
function RequireAny({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { can } = useAuth()
  return permissions.some(can) ? <>{children}</> : <NoAccessPage reason="Этот раздел недоступен для вашей роли" />
}

function Protected() {
  const { me, loading, error } = useAuth()
  if (loading) return <PageLoader fullScreen tip="Загрузка журналов…" />
  if (error || !me) return <NoAccessPage reason={error ?? 'Не удалось определить пользователя'} />
  return <AppLayout />
}

export default function App() {
  return (
    <ConfigProvider theme={antdTheme} locale={ruRU}>
      <AntApp>
        <BrowserRouter basename="/journals">
          <AuthProvider>
            <Routes>
              {DEV_LOGIN ? <Route path="/login" element={<DevLoginPage />} /> : null}
              <Route element={<Protected />}>
                <Route index element={<DashboardPage />} />
                <Route path="/medical" element={<Journal kind="medical" />} />
                <Route path="/technical" element={<Journal kind="technical" />} />
                <Route path="/ejournals" element={<RequireAny permissions={['ejournal:view']}><EJournalsPage /></RequireAny>} />
                <Route
                  path="/deletion-requests"
                  element={<RequireAny permissions={['medical:delete_signed', 'technical:delete_signed']}><DeletionRequestsPage /></RequireAny>}
                />
                <Route path="/catalog" element={<RequireAny permissions={['catalog:view']}><CatalogPage /></RequireAny>} />
                <Route path="/specialists" element={<RequireAny permissions={['catalog:view']}><SpecialistsPage /></RequireAny>} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}
