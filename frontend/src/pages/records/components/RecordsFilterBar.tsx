import { AutoComplete, Card, DatePicker, Input, Select, Space, App } from 'antd'
import { OrganizationSelect } from '../../../shared/components/CatalogSelects'
import type { Kind } from '../../../shared/types/api.types'
import type { RecordsFilters } from '../types'
import { MIN_SEARCH_LENGTH, useSearchSuggestions } from '../hooks/useSearchSuggestions'

interface Props {
  kind: Kind
  filters: RecordsFilters
  searchText: string
  isManager: boolean
  isClient: boolean
  searchPlaceholder: string
  /** Параметр поиска на сервере: driver_name для медосмотров, vehicle для техконтроля. */
  searchParam: string
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
  searchParam,
  onFilterChange,
  onSearchTextChange,
}: Props) {
  const { message } = App.useApp()
  const { suggestions, loading: suggesting } = useSearchSuggestions(kind, searchParam, searchText, filters)

  const applySearch = (value: string) => {
    const v = value.trim()
    if (v && v.length < MIN_SEARCH_LENGTH) {
      message.info(`Введите хотя бы ${MIN_SEARCH_LENGTH} символа`)
      return
    }
    onFilterChange({ text: v || undefined })
  }

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
        <AutoComplete
          value={searchText}
          options={suggestions}
          onChange={(value: string) => {
            onSearchTextChange(value)
            if (!value) onFilterChange({ text: undefined })
          }}
          onSelect={(value: string) => {
            onSearchTextChange(value)
            applySearch(value)
          }}
          notFoundContent={
            suggesting ? 'Поиск…' : searchText.trim().length >= MIN_SEARCH_LENGTH ? 'Ничего не найдено' : null
          }
          popupMatchSelectWidth={320}
        >
          <Input.Search allowClear placeholder={searchPlaceholder} onSearch={applySearch} />
        </AutoComplete>
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
