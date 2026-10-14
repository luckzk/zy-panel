import { create } from 'zustand';

/** 主题模式：浅色 / 深色 / 未来主义（v0 futuristic-dashboard 风格） */
export type ThemeMode = 'light' | 'dark' | 'futuristic';

interface ThemeState {
  mode: ThemeMode;
  /** 是否深色系（含未来主义），供图表等沿用旧逻辑 */
  dark: boolean;
  setMode: (mode: ThemeMode) => void;
}

const THEME_KEY = 'oci_panel_theme';

function readMode(): ThemeMode {
  const v = localStorage.getItem(THEME_KEY);
  if (v === 'light' || v === 'dark' || v === 'futuristic') return v;
  // 新用户默认进入未来主义主题
  return 'futuristic';
}

export const useThemeStore = create<ThemeState>()((set) => {
  const mode = readMode();
  return {
    mode,
    dark: mode !== 'light',
    setMode: (m) => {
      localStorage.setItem(THEME_KEY, m);
      set({ mode: m, dark: m !== 'light' });
    },
  };
});
