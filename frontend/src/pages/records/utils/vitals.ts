/**
 * Предзаполнение показателей медосмотра по ТЗ: случайное значение из допустимых диапазонов, чтобы записи
 * не выглядели одинаковыми. АД — от 110 до 138 / от 70 до 90 с шагом 2, пульс — от 60 до 89,
 * температура — от 36,2 до 36,9 с шагом 0,1. Медик может исправить любое значение.
 */
const pick = (from: number, to: number, step: number): number =>
  from + step * Math.floor(Math.random() * (Math.floor((to - from) / step) + 1))

export interface Vitals {
  bp_systolic: number
  bp_diastolic: number
  pulse: number
  temperature: number
}

export function randomVitals(): Vitals {
  return {
    bp_systolic: pick(110, 138, 2),
    bp_diastolic: pick(70, 90, 2),
    pulse: pick(60, 89, 1),
    temperature: pick(362, 369, 1) / 10,
  }
}

export const VITAL_FIELDS: (keyof Vitals)[] = ['bp_systolic', 'bp_diastolic', 'pulse', 'temperature']

/** Не больше дней в одном периоде: защита от случайного выбора года вместо месяца. */
export const MAX_PERIOD_DAYS = 31
