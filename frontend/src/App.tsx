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
import { JournalNotAvailable, NoAccessPage, NotFoundPage } from '@/pages/StatusPages'
import type { Kind } from '@/api/types'
import { antdTheme } from '@/theme/antdTheme'
import '@/styles/global.css'

function Journal({ kind }: { kind: Kind }) {
  const { hasJournal } = useAuth()
  return hasJournal(kind) ? <RecordsPage key={kind} kind={kind} /> : <JournalNotAvailable />
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
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}
