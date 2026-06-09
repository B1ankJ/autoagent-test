import type { ThemeConfig } from 'antd'
import { theme as antdTheme } from 'antd'

// Brand palette: cobalt + amber.
// Cobalt is the primary action color. Amber is reserved for warnings,
// running-state highlights, and the single "wake-up" accent per page.
export const brand = {
  cobalt50: '#EEF2FF',
  cobalt100: '#DCE3FF',
  cobalt500: '#2547D0',
  cobalt600: '#1F3CB8',
  cobalt700: '#192F94',
  amber50: '#FEF6E0',
  amber500: '#F59E0B',
  amber600: '#D97706',
}

// Neutral ramps. Light mode uses a near-white that's slightly warm (#F7F7F5)
// so the cobalt reads as cooler than the page; dark mode uses a desaturated
// near-black (#0B0D12) instead of pure black to avoid the OLED-burn aesthetic.
const neutralLight = {
  bg: '#F7F7F5',
  surface: '#FFFFFF',
  surfaceAlt: '#F1F1EE',
  border: '#E5E5E1',
  borderStrong: '#CFCFC9',
  text: '#0F1115',
  textMuted: '#5C5F66',
}

const neutralDark = {
  bg: '#0B0D12',
  surface: '#13161D',
  surfaceAlt: '#1A1E27',
  border: '#262B36',
  borderStrong: '#3A4151',
  text: '#E6E8EE',
  textMuted: '#8A8F9A',
}

const sharedTokens = {
  borderRadius: 6,
  borderRadiusLG: 8,
  borderRadiusSM: 4,
  controlHeight: 32,
  fontSize: 13,
  fontFamily:
    'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  fontFamilyCode:
    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
}

export const lightTheme: ThemeConfig = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    ...sharedTokens,
    colorPrimary: brand.cobalt500,
    colorInfo: brand.cobalt500,
    colorWarning: brand.amber500,
    colorBgBase: neutralLight.bg,
    colorBgContainer: neutralLight.surface,
    colorBgLayout: neutralLight.bg,
    colorBgElevated: neutralLight.surface,
    colorBorder: neutralLight.border,
    colorBorderSecondary: neutralLight.border,
    colorText: neutralLight.text,
    colorTextSecondary: neutralLight.textMuted,
    boxShadow: '0 1px 2px rgba(15, 17, 21, 0.06)',
    boxShadowSecondary: '0 4px 12px rgba(15, 17, 21, 0.06)',
  },
  components: {
    Layout: {
      headerBg: neutralLight.surface,
      siderBg: '#0F1115',
      bodyBg: neutralLight.bg,
      headerHeight: 52,
    },
    Menu: {
      darkItemBg: '#0F1115',
      darkItemSelectedBg: brand.cobalt500,
      darkSubMenuItemBg: '#0F1115',
      darkItemHoverBg: 'rgba(255,255,255,0.06)',
      darkItemColor: 'rgba(255,255,255,0.72)',
      darkItemHoverColor: '#FFFFFF',
      darkItemSelectedColor: '#FFFFFF',
      darkGroupTitleColor: 'rgba(255,255,255,0.42)',
    },
    Table: {
      headerBg: neutralLight.surfaceAlt,
      headerColor: neutralLight.textMuted,
      rowHoverBg: neutralLight.surfaceAlt,
      cellPaddingBlock: 10,
    },
    Card: {
      headerBg: 'transparent',
    },
    Button: {
      controlHeight: 32,
      paddingInline: 14,
    },
    Tag: {
      defaultBg: neutralLight.surfaceAlt,
    },
  },
}

export const darkTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    ...sharedTokens,
    colorPrimary: '#5B7CF7',
    colorInfo: '#5B7CF7',
    colorWarning: brand.amber500,
    colorBgBase: neutralDark.bg,
    colorBgContainer: neutralDark.surface,
    colorBgLayout: neutralDark.bg,
    colorBgElevated: neutralDark.surface,
    colorBorder: neutralDark.border,
    colorBorderSecondary: neutralDark.border,
    colorText: neutralDark.text,
    colorTextSecondary: neutralDark.textMuted,
    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.4)',
    boxShadowSecondary: '0 4px 16px rgba(0, 0, 0, 0.45)',
  },
  components: {
    Layout: {
      headerBg: neutralDark.surface,
      siderBg: '#070910',
      bodyBg: neutralDark.bg,
      headerHeight: 52,
    },
    Menu: {
      darkItemBg: '#070910',
      darkItemSelectedBg: brand.cobalt600,
      darkSubMenuItemBg: '#070910',
      darkItemHoverBg: 'rgba(255,255,255,0.05)',
      darkItemColor: 'rgba(230,232,238,0.78)',
      darkItemHoverColor: '#FFFFFF',
      darkItemSelectedColor: '#FFFFFF',
      darkGroupTitleColor: 'rgba(230,232,238,0.45)',
    },
    Table: {
      headerBg: neutralDark.surfaceAlt,
      headerColor: neutralDark.textMuted,
      rowHoverBg: neutralDark.surfaceAlt,
      cellPaddingBlock: 10,
    },
    Card: {
      headerBg: 'transparent',
    },
    Button: {
      controlHeight: 32,
      paddingInline: 14,
    },
    Tag: {
      defaultBg: neutralDark.surfaceAlt,
    },
  },
}

export const cssVariables = {
  light: {
    '--aa-bg': neutralLight.bg,
    '--aa-surface': neutralLight.surface,
    '--aa-surface-alt': neutralLight.surfaceAlt,
    '--aa-border': neutralLight.border,
    '--aa-border-strong': neutralLight.borderStrong,
    '--aa-text': neutralLight.text,
    '--aa-text-muted': neutralLight.textMuted,
    '--aa-cobalt': brand.cobalt500,
    '--aa-cobalt-soft': brand.cobalt50,
    '--aa-amber': brand.amber500,
    '--aa-amber-soft': brand.amber50,
    '--aa-mono': sharedTokens.fontFamilyCode,
  },
  dark: {
    '--aa-bg': neutralDark.bg,
    '--aa-surface': neutralDark.surface,
    '--aa-surface-alt': neutralDark.surfaceAlt,
    '--aa-border': neutralDark.border,
    '--aa-border-strong': neutralDark.borderStrong,
    '--aa-text': neutralDark.text,
    '--aa-text-muted': neutralDark.textMuted,
    '--aa-cobalt': '#5B7CF7',
    '--aa-cobalt-soft': 'rgba(91,124,247,0.16)',
    '--aa-amber': brand.amber500,
    '--aa-amber-soft': 'rgba(245,158,11,0.18)',
    '--aa-mono': sharedTokens.fontFamilyCode,
  },
}
