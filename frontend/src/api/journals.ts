import { api } from './client'
import type {
  AnyRecord,
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
