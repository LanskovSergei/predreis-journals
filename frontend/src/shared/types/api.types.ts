/** Типы ответов API журналов (по docs/openapi.json). */
export type Kind = 'medical' | 'technical'
export type Role = 'client' | 'dispatcher' | 'medic' | 'mechanic' | 'predreis' | 'admin' | 'superadmin'
export type RecordStatus = 'unsigned' | 'signed' | 'in_journal'
export type RecordSource = 'manual' | 'ocr' | 'epl'
export type Phase = 'pre' | 'post'
export type Result = 'admitted' | 'not_admitted'
export type HarmfulFactors = 'absent' | 'detected'
export type RecordAction = 'edit' | 'delete' | 'sign' | 'clear_note' | 'request_deletion'

export interface Me {
  user_id: string
  role: Role
  full_name: string | null
  organization_id: string | null
  permissions: string[]
  journals: Kind[]
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface SignatureInfo {
  cert_serial: string | null
  cert_subject: string | null
  cert_valid_from: string | null
  cert_valid_to: string | null
  signed_at: string | null
}

interface Snapshot {
  organization?: { inn?: string; name?: string; short_name?: string | null }
  specialist?: { full_name?: string }
  driver?: { full_name?: string; birth_date?: string | null; gender?: string | null }
  vehicle?: { brand?: string; model?: string; plate?: string }
}

interface RecordBase {
  id: string
  status: RecordStatus
  source: RecordSource
  performed_at: string
  result: Result
  note?: string | null
  has_note?: boolean
  deletion_pending?: boolean
  in_journal_reserved?: boolean
  signature: SignatureInfo | null
  signing_status?: string | null
  signing_error?: string | null
  actions?: RecordAction[]
  snapshot?: Snapshot
  organization_id?: string
  specialist_user_id?: string
}

export interface MedicalRecord extends RecordBase {
  phase: Phase
  driver_id?: string
  complaints?: string
  bp_systolic?: number
  bp_diastolic?: number
  pulse?: number
  temperature?: string
  alcohol_permille?: string
  harmful_factors?: HarmfulFactors | null
  harmful_factors_note?: string | null
  /** Только в ответе для клиента: показатели скрыты, ФИО водителя — отдельным полем */
  driver_full_name?: string
  specialist_name?: string | null
}

export interface TechnicalRecord extends RecordBase {
  vehicle_id?: string
  driver_id?: string | null
  odometer?: number
}

export type AnyRecord = MedicalRecord | TechnicalRecord

export interface RecordCounters {
  to_sign: number
  signed: number
  total: number
}

export interface Stats {
  organizations?: { active: number; total: number } | null
  drivers?: { active: number; total: number } | null
  medical?: RecordCounters | null
  technical?: RecordCounters | null
}

export interface Organization {
  id: string
  inn: string
  name: string
  short_name: string | null
  is_active: boolean
}

export interface Driver {
  id: string
  organization_id: string
  full_name: string
  birth_date: string | null
}

export interface Vehicle {
  id: string
  organization_id: string
  brand: string
  model: string
  plate: string
}

export interface Specialist {
  user_id: string
  full_name: string
  status: 'active' | 'expired' | 'missing'
  valid_to: string | null
}

export interface MyCertificates {
  status: 'active' | 'expired' | 'missing'
  valid_to: string | null
}

export interface SignBatchResult {
  signed: number
  failed: number
  results: { record_id: string; ok: boolean; code?: string | null; message?: string | null }[]
}

export interface DeleteBatchResult {
  deleted: number
  failed: number
  results: { record_id: string; ok: boolean; code?: string | null; message?: string | null }[]
}
