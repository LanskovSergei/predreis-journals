/**
 * Фирменный стиль «Предрейс ONLINE» — копия frontend/src/theme/brand.ts платформы.
 * Журналы открываются внутри платформы и должны выглядеть так же: при смене брендбука
 * обновлять оба файла одинаково.
 */
export const brandColors = {
  primary: '#1C1F41',
  primaryHover: '#2A2E5C',
  primaryActive: '#141632',
  secondary: '#8285BF',
  secondaryHover: '#9A9DCC',
  accent: '#674A95',
  text: '#262626',
  textSecondary: '#5C5C6A',
  textOnPrimary: '#FFFFFF',
  background: '#F5F5F5',
  surface: '#FFFFFF',
  border: '#C5CECD',
  tagBg: '#E8EBF5',
  tagText: '#1C1F41',
} as const

export const brandFonts = {
  display: "'TT Autonomous', 'Open Sans', sans-serif",
  body: "'Open Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
} as const
