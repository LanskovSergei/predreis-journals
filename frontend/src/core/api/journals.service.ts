import { httpClient } from './http.client'
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
} from '../../shared/types/api.types'

const BASE_PATH = '/api/v1'

export class JournalsService {
  static async getMe(): Promise<Me> {
    const { data } = await httpClient.get(`${BASE_PATH}/me`)
    return data
  }

  static async getStats(): Promise<Stats> {
    const { data } = await httpClient.get(`${BASE_PATH}/stats/overview`)
    return data
  }

  static async getMyCertificates(): Promise<MyCertificates> {
    const { data } = await httpClient.get(`${BASE_PATH}/me/certificates`)
    return data
  }

  static async getRecords(kind: Kind, params: Record<string, unknown>): Promise<Page<AnyRecord>> {
    const { data } = await httpClient.get(`${BASE_PATH}/${kind}/records`, { params })
    return data
  }

  static async createRecord(kind: Kind, body: Record<string, unknown>): Promise<AnyRecord> {
    const { data } = await httpClient.post(`${BASE_PATH}/${kind}/records`, body)
    return data
  }

  static async updateRecord(kind: Kind, id: string, body: Record<string, unknown>): Promise<AnyRecord> {
    const { data } = await httpClient.patch(`${BASE_PATH}/${kind}/records/${id}`, body)
    return data
  }

  static async deleteRecord(kind: Kind, id: string): Promise<void> {
    await httpClient.delete(`${BASE_PATH}/${kind}/records/${id}`)
  }

  static async deleteRecordsBatch(kind: Kind, ids: string[]): Promise<DeleteBatchResult> {
    const { data } = await httpClient.post(`${BASE_PATH}/${kind}/records/delete`, { record_ids: ids })
    return data
  }

  static async signRecordsBatch(kind: Kind, ids: string[]): Promise<SignBatchResult> {
    const { data } = await httpClient.post(`${BASE_PATH}/${kind}/records/sign`, { record_ids: ids })
    return data
  }

  static async clearRecordNote(kind: Kind, id: string): Promise<void> {
    await httpClient.post(`${BASE_PATH}/${kind}/records/${id}/clear-note`)
  }

  static async requestRecordDeletion(kind: Kind, id: string, reason: string): Promise<void> {
    await httpClient.post(`${BASE_PATH}/${kind}/records/${id}/deletion-request`, { reason })
  }

  static async getStandardTime(kind: Kind, params: Record<string, string>): Promise<{ time: string | null }> {
    const { data } = await httpClient.get(`${BASE_PATH}/${kind}/records/standard-time`, { params })
    return data
  }

  static async searchOrganizations(q?: string): Promise<Organization[]> {
    const params = { q: q || undefined, only_active: true, page_size: 50 }
    const { data } = await httpClient.get(`${BASE_PATH}/catalog/organizations`, { params })
    return data.items
  }

  static async searchDrivers(organizationId: string, q?: string): Promise<Driver[]> {
    const params = { organization_id: organizationId, q: q || undefined, page_size: 50 }
    const { data } = await httpClient.get(`${BASE_PATH}/catalog/drivers`, { params })
    return data.items
  }

  static async searchVehicles(organizationId: string, q?: string): Promise<Vehicle[]> {
    const params = { organization_id: organizationId, q: q || undefined, page_size: 50 }
    const { data } = await httpClient.get(`${BASE_PATH}/catalog/vehicles`, { params })
    return data.items
  }

  static async getSpecialists(role: 'medic' | 'mechanic'): Promise<Specialist[]> {
    const { data } = await httpClient.get(`${BASE_PATH}/specialists`, { params: { role } })
    return data.items
  }

  static async exportPdf(kind: Kind, body: Record<string, unknown>): Promise<{ blob: Blob; filename: string }> {
    const response = await httpClient.post(`${BASE_PATH}/exports/${kind}`, body, { responseType: 'blob' })
    const header = String(response.headers['content-disposition'] ?? '')
    const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
    const plain = /filename="?([^";]+)"?/i.exec(header)
    const filename = star ? decodeURIComponent(star[1]) : plain ? plain[1] : `${kind}.pdf`
    
    return { blob: response.data as Blob, filename }
  }

  static async devLogin(email: string, password: string): Promise<string> {
    const { data } = await httpClient.post(`${BASE_PATH}/auth/login`, { email, password })
    return data.access_token
  }
}
