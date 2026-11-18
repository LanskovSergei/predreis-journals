import { useEffect, useState } from 'react'
import { Select } from 'antd'
import { JournalsService } from '../../core/api/journals.service'

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
    async (q) => (await JournalsService.searchOrganizations(q)).map((o) => ({ value: o.id, label: o.short_name || o.name })),
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

/** refreshKey: смените значение, чтобы перечитать список (например, после добавления водителя). */
export function DriverSelect({
  organizationId,
  refreshKey,
  value,
  onChange,
  ...rest
}: SelectProps & { organizationId?: string; refreshKey?: number }) {
  const { options, loading, search } = useRemoteOptions(
    async (q) =>
      organizationId
        ? (await JournalsService.searchDrivers(organizationId, q)).map((d) => ({ value: d.id, label: d.full_name }))
        : [],
    [organizationId, refreshKey],
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

/** refreshKey: смените значение, чтобы перечитать список (например, после добавления ТС). */
export function VehicleSelect({
  organizationId,
  refreshKey,
  value,
  onChange,
  ...rest
}: SelectProps & { organizationId?: string; refreshKey?: number }) {
  const { options, loading, search } = useRemoteOptions(
    async (q) =>
      organizationId
        ? (await JournalsService.searchVehicles(organizationId, q)).map((v) => ({
            value: v.id,
            label: `${v.brand} ${v.model}, ${v.plate}`,
          }))
        : [],
    [organizationId, refreshKey],
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
    async () => (await JournalsService.getSpecialists(role)).map((s) => ({ value: s.user_id, label: s.full_name })),
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
