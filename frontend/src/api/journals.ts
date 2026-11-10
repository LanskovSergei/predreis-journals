import { api } from './client'
import type {
  AnyRecord,
  DeletionRequest,
  DeletionStatus,
  DriverFull,
  EJournal,
  OrganizationFull,
  SpecialistsList,
  VehicleFull,
  DeleteBatchResult,
  Driver,
  Kind,
  Me,
  MyCertificates,
  Organization,
  Page,
  SignBatchResult,
  Specialist,
  Stats,
  Vehicle,
} from './types'

const P = '/api/v1'

export const fetchMe = async (): Promise<Me> => (await api.get(`${P}/me`)).data
export const fetchStats = async (): Promise<Stats> => (await api.get(`${P}/stats/overview`)).data
export const fetchMyCertificates = async (): Promise<MyCertificates> =>
  (await api.get(`${P}/me/certificates`)).data

export async function fetchRecords(kind: Kind, params: Record<string, unknown>): Promise<Page<AnyRecord>> {
  return (await api.get(`${P}/${kind}/records`, { params })).data
}

export const createRecord = async (kind: Kind, body: Record<string, unknown>): Promise<AnyRecord> =>
  (await api.post(`${P}/${kind}/records`, body)).data

export const updateRecord = async (kind: Kind, id: string, body: Record<string, unknown>): Promise<AnyRecord> =>
  (await api.patch(`${P}/${kind}/records/${id}`, body)).data

export const deleteRecord = async (kind: Kind, id: string): Promise<void> => {
  await api.delete(`${P}/${kind}/records/${id}`)
}

export const deleteRecords = async (kind: Kind, ids: string[]): Promise<DeleteBatchResult> =>
  (await api.post(`${P}/${kind}/records/delete`, { record_ids: ids })).data

export const signRecords = async (kind: Kind, ids: string[]): Promise<SignBatchResult> =>
  (await api.post(`${P}/${kind}/records/sign`, { record_ids: ids })).data

export const clearNote = async (kind: Kind, id: string): Promise<void> => {
  await api.post(`${P}/${kind}/records/${id}/clear-note`)
}

export const requestDeletion = async (kind: Kind, id: string, reason: string): Promise<void> => {
  await api.post(`${P}/${kind}/records/${id}/deletion-request`, { reason })
}

export async function fetchStandardTime(
  kind: Kind,
  params: Record<string, string>,
): Promise<{ time: string | null }> {
  return (await api.get(`${P}/${kind}/records/standard-time`, { params })).data
}

export async function searchOrganizations(q?: string): Promise<Organization[]> {
  const params = { q: q || undefined, only_active: true, page_size: 50 }
  return (await api.get(`${P}/catalog/organizations`, { params })).data.items
}

export async function searchDrivers(organizationId: string, q?: string): Promise<Driver[]> {
  const params = { organization_id: organizationId, q: q || undefined, page_size: 50 }
  return (await api.get(`${P}/catalog/drivers`, { params })).data.items
}

export async function searchVehicles(organizationId: string, q?: string): Promise<Vehicle[]> {
  const params = { organization_id: organizationId, q: q || undefined, page_size: 50 }
  return (await api.get(`${P}/catalog/vehicles`, { params })).data.items
}

export async function fetchSpecialists(role: 'medic' | 'mechanic'): Promise<Specialist[]> {
  return (await api.get(`${P}/specialists`, { params: { role } })).data.items
}

/** Выгрузка PDF: возвращает файл и имя из Content-Disposition. */
export async function exportPdf(kind: Kind, body: Record<string, unknown>): Promise<{ blob: Blob; filename: string }> {
  const response = await api.post(`${P}/exports/${kind}`, body, { responseType: 'blob' })
  const header = String(response.headers['content-disposition'] ?? '')
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  const plain = /filename="?([^";]+)"?/i.exec(header)
  const filename = star ? decodeURIComponent(star[1]) : plain ? plain[1] : `${kind}.pdf`
  return { blob: response.data as Blob, filename }
}

export async function devLogin(email: string, password: string): Promise<string> {
  return (await api.post(`${P}/auth/login`, { email, password })).data.access_token
}

// ---- Электронные журналы ----
export const fetchEJournals = async (params: Record<string, unknown>): Promise<EJournal[]> => {
  const data = (await api.get(`${P}/ejournals`, { params })).data
  return Array.isArray(data) ? data : data.items
}
export const createEJournal = async (body: Record<string, unknown>): Promise<EJournal> =>
  (await api.post(`${P}/ejournals`, body)).data
export const submitEJournal = async (id: string): Promise<EJournal> => (await api.post(`${P}/ejournals/${id}/submit`)).data
export const signEJournal = async (id: string): Promise<EJournal> => (await api.post(`${P}/ejournals/${id}/sign`)).data
export const rejectEJournal = async (id: string, reason: string): Promise<EJournal> =>
  (await api.post(`${P}/ejournals/${id}/reject`, { reason })).data
export const deleteEJournal = async (id: string): Promise<void> => {
  await api.delete(`${P}/ejournals/${id}`)
}
/** Файл журнала: PDF для просмотра или ZIP подписанного журнала. */
export async function fetchEJournalFile(id: string, what: 'preview' | 'download'): Promise<{ blob: Blob; filename: string }> {
  const response = await api.get(`${P}/ejournals/${id}/${what}`, { responseType: 'blob' })
  const header = String(response.headers['content-disposition'] ?? '')
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  const plain = /filename="?([^";]+)"?/i.exec(header)
  const fallback = what === 'preview' ? `journal-${id}.pdf` : `journal-${id}.zip`
  return { blob: response.data as Blob, filename: star ? decodeURIComponent(star[1]) : plain ? plain[1] : fallback }
}

// ---- Запросы на удаление ----
export const fetchDeletionRequests = async (status: DeletionStatus): Promise<DeletionRequest[]> => {
  const data = (await api.get(`${P}/deletion-requests`, { params: { status_filter: status } })).data
  return Array.isArray(data) ? data : data.items
}
export const resolveDeletionRequest = async (id: string, decision: 'approve' | 'reject', comment: string) =>
  (await api.post(`${P}/deletion-requests/${id}/${decision}`, { comment: comment || null })).data as DeletionRequest
export const fetchRecord = async (kind: Kind, id: string): Promise<AnyRecord> =>
  (await api.get(`${P}/${kind}/records/${id}`)).data

// ---- Каталог ----
export async function fetchOrganizationsPage(params: Record<string, unknown>): Promise<Page<OrganizationFull>> {
  return (await api.get(`${P}/catalog/organizations`, { params })).data
}
export const createOrganization = async (body: Record<string, unknown>): Promise<OrganizationFull> =>
  (await api.post(`${P}/catalog/organizations`, body)).data
export const updateOrganization = async (id: string, body: Record<string, unknown>): Promise<OrganizationFull> =>
  (await api.patch(`${P}/catalog/organizations/${id}`, body)).data
export async function fetchDriversPage(params: Record<string, unknown>): Promise<Page<DriverFull>> {
  return (await api.get(`${P}/catalog/drivers`, { params })).data
}
export const createDriver = async (body: Record<string, unknown>) =>
  (await api.post(`${P}/catalog/drivers`, { drivers: [body] })).data
export async function fetchVehiclesPage(params: Record<string, unknown>): Promise<Page<VehicleFull>> {
  return (await api.get(`${P}/catalog/vehicles`, { params })).data
}
export const createVehicle = async (body: Record<string, unknown>) =>
  (await api.post(`${P}/catalog/vehicles`, { vehicles: [body] })).data

// ---- Специалисты ----
export const fetchSpecialistsList = async (role: 'medic' | 'mechanic'): Promise<SpecialistsList> =>
  (await api.get(`${P}/specialists`, { params: { role } })).data
