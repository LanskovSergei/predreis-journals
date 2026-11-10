import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { TokenService } from '../auth/token.service'
import { PageLoader } from '../../shared/components/PageLoader'
import { AppLayout } from '../layout/AppLayout'
import { DashboardPage } from '../../pages/dashboard/DashboardPage'
import { DevLoginPage } from '../../pages/auth/DevLoginPage'
import { RecordsPage } from '../../pages/records/RecordsPage'
import { EJournalsPage } from '../../pages/ejournals/EJournalsPage'
import { DeletionRequestsPage } from '../../pages/deletion-requests/DeletionRequestsPage'
import { CatalogPage } from '../../pages/catalog/CatalogPage'
import { SpecialistsPage } from '../../pages/specialists/SpecialistsPage'
import { ComingSoonPage, JournalNotAvailable, NoAccessPage, NotFoundPage } from '../../pages/status/StatusPages'
import type { Kind } from '../../shared/types/api.types'

function JournalRoute({ kind }: { kind: Kind }) {
  const { hasJournalAccess } = useAuth()
  return hasJournalAccess(kind) ? <RecordsPage key={kind} kind={kind} /> : <JournalNotAvailable />
}

function RequireAny({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { hasPermission } = useAuth()
  return permissions.some(hasPermission) ? <>{children}</> : <NoAccessPage reason="Этот раздел недоступен для вашей роли" />
}

function ProtectedRoute() {
  const { user, isLoading, authError } = useAuth()
  
  if (isLoading) return <PageLoader fullScreen tip="Загрузка журналов…" />
  if (authError || !user) return <NoAccessPage reason={authError ?? 'Не удалось определить пользователя'} />
  if (user.ui_enabled === false) return <ComingSoonPage />
  
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
      { path: 'ejournals', element: <RequireAny permissions={['ejournal:view']}><EJournalsPage /></RequireAny> },
      { path: 'deletion-requests', element: <RequireAny permissions={['medical:delete_signed', 'technical:delete_signed']}><DeletionRequestsPage /></RequireAny> },
      { path: 'catalog', element: <RequireAny permissions={['catalog:view']}><CatalogPage /></RequireAny> },
      { path: 'specialists', element: <RequireAny permissions={['catalog:view']}><SpecialistsPage /></RequireAny> },
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
