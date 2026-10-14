import { theme as antdTheme } from 'antd';
import type { ThemeConfig } from 'antd';

/**
 * 未来主义主题（对标 v0 futuristic-dashboard 模板真实预览）：
 * 深蓝黑底 #070b14 + 霓虹青 #22d3ee 主色 + 散景光斑背景 + 半透明玻璃卡片。
 */
export const FUTURISTIC_ACCENT = '#22d3ee'; // 霓虹青：主操作/高亮（模板主强调色）
export const FUTURISTIC_CYAN = '#22d3ee'; // 青色：数据线/链接
export const FUTURISTIC_BG = '#070b14'; // 页面底：冷蓝黑

/** ECharts 配色：青 → 紫 → 蓝 → 粉 → 青绿 → 琥珀（模板图表语言） */
export const FUTURISTIC_CHART_COLORS = [
  '#22d3ee',
  '#a855f7',
  '#3b82f6',
  '#ec4899',
  '#2dd4bf',
  '#f59e0b',
];

export const futuristicTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: FUTURISTIC_ACCENT,
    colorInfo: FUTURISTIC_CYAN,
    colorSuccess: '#4ade80',
    colorWarning: '#fbbf24',
    colorError: '#f87171',
    colorLink: FUTURISTIC_CYAN,

    colorBgBase: FUTURISTIC_BG,
    colorBgLayout: FUTURISTIC_BG,
    colorBgContainer: '#0d1420',
    colorBgElevated: '#0f1729',
    colorBgSpotlight: '#0f1729',

    colorBorder: 'rgba(148, 163, 184, 0.16)',
    colorBorderSecondary: 'rgba(148, 163, 184, 0.09)',

    colorTextBase: '#eef2f7',
    colorTextSecondary: '#8b93a7',
    colorTextTertiary: '#5b6478',
    colorTextQuaternary: '#3d4457',

    colorFill: 'rgba(148, 163, 184, 0.12)',
    colorFillSecondary: 'rgba(148, 163, 184, 0.08)',

    borderRadius: 10,
    borderRadiusLG: 14,
    borderRadiusSM: 8,

    fontSize: 14,
    fontSizeHeading1: 32,
    fontSizeHeading2: 24,

    boxShadow: '0 12px 40px rgba(0, 0, 0, 0.55)',
    boxShadowSecondary: '0 6px 24px rgba(0, 0, 0, 0.5)',

    lineWidth: 1,
  },
  components: {
    Layout: {
      bodyBg: FUTURISTIC_BG,
      headerBg: '#0a0f1c',
      siderBg: '#0a0f1c',
      footerBg: FUTURISTIC_BG,
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
      darkItemSelectedBg: 'rgba(34, 211, 238, 0.10)',
      darkItemSelectedColor: FUTURISTIC_ACCENT,
      darkItemColor: '#8b93a7',
      darkItemHoverBg: 'rgba(148, 163, 184, 0.08)',
      darkItemHoverColor: '#eef2f7',
      itemBorderRadius: 10,
      itemMarginInline: 8,
    },
    Card: {
      headerBg: 'transparent',
      colorBorderSecondary: 'rgba(148, 163, 184, 0.12)',
    },
    Table: {
      headerBg: 'rgba(148, 163, 184, 0.05)',
      headerColor: '#8b93a7',
      rowHoverBg: 'rgba(34, 211, 238, 0.04)',
      borderColor: 'rgba(148, 163, 184, 0.09)',
    },
    Input: {
      colorBgContainer: '#0b1220',
      colorBorder: 'rgba(148, 163, 184, 0.18)',
      hoverBorderColor: FUTURISTIC_ACCENT,
    },
    Select: {
      colorBgContainer: '#0b1220',
      colorBorder: 'rgba(148, 163, 184, 0.18)',
      optionSelectedBg: 'rgba(34, 211, 238, 0.12)',
    },
    Modal: {
      contentBg: '#0d1424',
      headerBg: 'transparent',
    },
    Drawer: {
      colorBgElevated: '#0d1424',
    },
    Tabs: {
      itemSelectedColor: FUTURISTIC_ACCENT,
      inkBarColor: FUTURISTIC_ACCENT,
      itemHoverColor: FUTURISTIC_CYAN,
    },
    Tag: {
      defaultBg: 'rgba(148, 163, 184, 0.10)',
    },
    Statistic: {
      contentFontSize: 30,
      titleFontSize: 13,
    },
    Alert: {
      colorInfoBg: 'rgba(34, 211, 238, 0.08)',
      colorSuccessBg: 'rgba(74, 222, 128, 0.08)',
      colorWarningBg: 'rgba(251, 191, 36, 0.08)',
      colorErrorBg: 'rgba(248, 113, 113, 0.08)',
    },
    Progress: {
      defaultColor: FUTURISTIC_CYAN,
    },
    Switch: {
      colorPrimary: FUTURISTIC_ACCENT,
    },
    Slider: {
      colorPrimary: FUTURISTIC_CYAN,
      colorPrimaryBorder: FUTURISTIC_CYAN,
    },
    Badge: {
      colorPrimary: FUTURISTIC_ACCENT,
    },
  },
};
