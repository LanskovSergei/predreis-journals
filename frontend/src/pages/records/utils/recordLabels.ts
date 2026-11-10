import type { AnyRecord, MedicalRecord } from '../../../shared/types/api.types'

export const getDriverName = (r: AnyRecord) =>
  (r as MedicalRecord).driver_full_name ?? r.snapshot?.driver?.full_name ?? '—'

export const getVehicleLabel = (r: AnyRecord) => {
  const v = r.snapshot?.vehicle
  return v ? `${v.brand ?? ''} ${v.model ?? ''}, ${v.plate ?? ''}`.trim() : '—'
}

export const getOrgName = (r: AnyRecord) =>
  r.snapshot?.organization?.short_name || r.snapshot?.organization?.name || '—'
