import type { Dayjs } from 'dayjs'

export interface RecordsFilters {
  organizationId?: string
  range?: [Dayjs | null, Dayjs | null] | null
  text?: string
  result?: string
  signed?: string
  note?: string
}
