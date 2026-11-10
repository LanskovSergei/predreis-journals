import { useEffect, useState } from 'react'
import { Select } from 'antd'
import { fetchSpecialists, searchDrivers, searchOrganizations, searchVehicles } from '@/api/journals'

interface Option {
  value: string
  label: string
}

/** Выпадающий список с поиском на сервере (организации, водители, ТС). */
function useRemoteOptions(load: (q?: string) => Promise<Option[]>, deps: unknown[]) {
  const [options, setOptions] = useState<Option[]>([])
  const [loading, setLoading] = useState(false)
  const search = async (q?: string) => {
    setLoading(true)
    try {
      setOptions(await load(q))
    } catch {
      setOptions([])
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    void search()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { options, loading, search }
}

type SelectProps = {
  value?: string
  onChange?: (value: string | undefined) => void
  placeholder?: string
  disabled?: boolean
  allowClear?: boolean
  className?: string
}

export function OrganizationSelect({ value, onChange, placeholder = 'Организация', ...rest }: SelectProps) {
  const { options, loading, search } = useRemoteOptions(
    async (q) => (await searchOrganizations(q)).map((o) => ({ value: o.id, label: o.short_name || o.name })),
    [],
  )
  return (
    <Select
      showSearch={{ filterOption: false, onSearch: (q) => void search(q) }}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      loading={loading}
      options={options}
      notFoundContent={loading ? 'Поиск…' : 'Ничего не найдено'}
      {...rest}
    />
  )
}

export function DriverSelect({ organizationId, value, onChange, ...rest }: SelectProps & { organizationId?: string }) {
  const { options, loading, search } = useRemoteOptions(
    async (q) =>
      organizationId
        ? (await searchDrivers(organizationId, q)).map((d) => ({ value: d.id, label: d.full_name }))
        : [],
    [organizationId],
  )
  return (
    <Select
      showSearch={{ filterOption: false, onSearch: (q) => void search(q) }}
      value={value}
      onChange={onChange}
      placeholder={organizationId ? 'Водитель' : 'Сначала выберите организацию'}
      disabled={!organizationId}
      loading={loading}
      options={options}
      notFoundContent={loading ? 'Поиск…' : 'Ничего не найдено'}
      {...rest}
    />
  )
}

export function VehicleSelect({ organizationId, value, onChange, ...rest }: SelectProps & { organizationId?: string }) {
  const { options, loading, search } = useRemoteOptions(
    async (q) =>
      organizationId
        ? (await searchVehicles(organizationId, q)).map((v) => ({
            value: v.id,
            label: `${v.brand} ${v.model}, ${v.plate}`,
          }))
        : [],
    [organizationId],
  )
  return (
    <Select
      showSearch={{ filterOption: false, onSearch: (q) => void search(q) }}
      value={value}
      onChange={onChange}
      placeholder={organizationId ? 'Транспортное средство' : 'Сначала выберите организацию'}
      disabled={!organizationId}
      loading={loading}
      options={options}
      notFoundContent={loading ? 'Поиск…' : 'Ничего не найдено'}
      {...rest}
    />
  )
}

export function SpecialistSelect({ role, value, onChange, ...rest }: SelectProps & { role: 'medic' | 'mechanic' }) {
  const { options, loading } = useRemoteOptions(
    async () => (await fetchSpecialists(role)).map((s) => ({ value: s.user_id, label: s.full_name })),
    [role],
  )
  return (
    <Select
      showSearch={{ optionFilterProp: 'label' }}
      value={value}
      onChange={onChange}
      placeholder={role === 'medic' ? 'Медик' : 'Механик'}
      loading={loading}
      options={options}
      {...rest}
    />
  )
}
