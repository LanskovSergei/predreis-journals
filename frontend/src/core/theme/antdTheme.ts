import type { ThemeConfig } from 'antd'
import { brandColors, brandFonts } from './brand'

export { brandColors, brandFonts } from './brand'

/** Тема Ant Design — та же, что у платформы (frontend/src/theme/antdTheme.ts). */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: brandColors.primary,
    colorInfo: brandColors.secondary,
    colorLink: brandColors.accent,
    colorSuccess: '#2E7D32',
    colorWarning: '#ED6C02',
    colorError: '#C62828',
    colorText: brandColors.text,
    colorTextSecondary: brandColors.textSecondary,
    colorBgLayout: brandColors.background,
    colorBgContainer: brandColors.surface,
    colorBorder: brandColors.border,
    borderRadius: 8,
    fontFamily: brandFonts.body,
    fontSize: 14,
    controlHeight: 40,
  },
  components: {
    Layout: {
      headerBg: brandColors.surface,
      siderBg: brandColors.primary,
      bodyBg: brandColors.background,
      triggerBg: brandColors.primaryActive,
    },
    Menu: {
      darkItemBg: brandColors.primary,
      darkSubMenuItemBg: brandColors.primaryActive,
      darkItemSelectedBg: 'rgba(255, 255, 255, 0.14)',
      darkItemSelectedColor: brandColors.textOnPrimary,
      darkItemHoverBg: 'rgba(255, 255, 255, 0.08)',
    },
    Button: { primaryShadow: '0 2px 0 rgba(28, 31, 65, 0.18)', fontWeight: 600 },
    Card: { borderRadiusLG: 12 },
    Typography: { fontFamilyCode: brandFonts.body },
  },
}
