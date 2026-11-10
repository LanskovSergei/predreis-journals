import dayjs, { type Dayjs } from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

/**
 * Журналы ведутся по московскому времени (как выгрузки PDF и «стандартное время» на сервере),
 * независимо от часового пояса компьютера пользователя.
 */
export const BUSINESS_TZ = 'Europe/Moscow'

/** Момент из API → московское время для показа. */
export const inBusinessTz = (iso: string): Dayjs => dayjs(iso).tz(BUSINESS_TZ)

/**
 * Значение для поля даты и времени: те же «часы на стене», что в Москве, но объектом в часовом
 * поясе браузера (так поле показывает ровно московские цифры).
 */
export const toPickerValue = (iso: string): Dayjs => dayjs(inBusinessTz(iso).format('YYYY-MM-DDTHH:mm:ss'))

/** Сейчас по Москве — значение по умолчанию для поля даты и времени. */
export const nowForPicker = (): Dayjs => dayjs(dayjs().tz(BUSINESS_TZ).format('YYYY-MM-DDTHH:mm:00'))

/** Значение поля (московские «часы на стене») → момент для API с московским смещением. */
export const fromPickerValue = (value: Dayjs): string =>
  dayjs.tz(value.format('YYYY-MM-DDTHH:mm:00'), BUSINESS_TZ).format()
