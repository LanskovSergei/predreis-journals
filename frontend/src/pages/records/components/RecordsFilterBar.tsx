import { Card, DatePicker, Input, Select, Space, App } from 'antd'
import { OrganizationSelect } from '../../../shared/components/CatalogSelects'
import type { Kind } from '../../../shared/types/api.types'
import type { RecordsFilters } from '../types'

interface Props {
  kind: Kind
  filters: RecordsFilters
  searchText: string
  isManager: boolean
  isClient: boolean
  searchPlaceholder: string
  onFilterChange: (patch: Partial<RecordsFilters>) => void
  onSearchTextChange: (text: string) => void
}

export function RecordsFilterBar({
  kind,
  filters,
  searchText,
  isManager,
  isClient,
  searchPlaceholder,
  onFilterChange,
  onSearchTextChange,
}: Props) {
  const { message } = App.useApp()

  return (
    <Card>
      <Space wrap className="filterBar">
        {isManager && (
          <OrganizationSelect
            allowClear
            value={filters.organizationId}
            onChange={(v) => onFilterChange({ organizationId: v })}
          />
        )}
        <DatePicker.RangePicker
          format="DD.MM.YYYY"
          value={filters.range ?? null}
          onChange={(values) => onFilterChange({ range: values as RecordsFilters['range'] })}
          placeholder={['С даты', 'По дату']}
        />
        <Input.Search
          allowClear
          placeholder={searchPlaceholder}
          value={searchText}
          onChange={(e) => {
            onSearchTextChange(e.target.value)
            if (!e.target.value) onFilterChange({ text: undefined })
          }}
          onSearch={(value) => {
            const v = value.trim()
            if (v && v.length < 3) {
              message.info('Введите хотя бы 3 символа')
              return
            }
            onFilterChange({ text: v || undefined })
          }}
        />
        <Select
          allowClear
          placeholder={kind === 'medical' ? 'Заключение' : 'Результат'}
          value={filters.result}
          onChange={(v) => onFilterChange({ result: v })}
          options={[
            { value: 'admitted', label: 'Допущен' },
            { value: 'not_admitted', label: 'Не допущен' },
          ]}
        />
        {!isClient && (
          <Select
            allowClear
            placeholder="Подпись"
            value={filters.signed}
            onChange={(v) => onFilterChange({ signed: v })}
            options={[
              { value: '0', label: 'Не подписанные' },
              { value: '1', label: 'Подписанные' },
            ]}
          />
        )}
        {!isClient && (
          <Select
            allowClear
            placeholder="Примечание"
            value={filters.note}
            onChange={(v) => onFilterChange({ note: v })}
            options={[
              { value: '1', label: 'С примечанием' },
              { value: '0', label: 'Без примечания' },
            ]}
          />
        )}
      </Space>
    </Card>
  )
}
