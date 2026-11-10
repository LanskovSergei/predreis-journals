import { createBrowserRouter, RouterProvider, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { TokenService } from '../auth/token.service'
import { PageLoader } from '../../shared/components/PageLoader'
import { AppLayout } from '../layout/AppLayout'
import { DashboardPage } from '../../pages/dashboard/DashboardPage'
import { DevLoginPage } from '../../pages/auth/DevLoginPage'
import { RecordsPage } from '../../pages/records/RecordsPage'
import { JournalNotAvailable, NoAccessPage, NotFoundPage } from '../../pages/status/StatusPages'
import type { Kind } from '../../shared/types/api.types'

function JournalRoute({ kind }: { kind: Kind }) {
  const { hasJournalAccess } = useAuth()
  return hasJournalAccess(kind) ? <RecordsPage key={kind} kind={kind} /> : <JournalNotAvailable />
}

function ProtectedRoute() {
  const { user, isLoading, authError } = useAuth()
  
  if (isLoading) return <PageLoader fullScreen tip="Загрузка журналов…" />
  if (authError || !user) return <NoAccessPage reason={authError ?? 'Не удалось определить пользователя'} />
  
  return <AppLayout />
}

const routes = [
  {
    path: '/',
    element: <ProtectedRoute />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'medical', element: <JournalRoute kind="medical" /> },
      { path: 'technical', element: <JournalRoute kind="technical" /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

if (TokenService.isDevLogin) {
  routes.unshift({
    path: '/login',
    element: <DevLoginPage />,
    children: []
  })
}

export const appRouter = createBrowserRouter(routes, {
  basename: '/journals',
})

export function AppRouter() {
  return <RouterProvider router={appRouter} />
}
