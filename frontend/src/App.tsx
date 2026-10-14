import { useEffect, useMemo } from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { useThemeStore } from './stores/theme';
import { futuristicTheme } from './theme/futuristic';
import FuturisticBackground from './components/FuturisticBackground';
import './theme/futuristic.css';

/** 应用入口：全局 ConfigProvider（中文 + 三主题）挂载路由 */
function App() {
  const mode = useThemeStore((s) => s.mode);

  const themeConfig = useMemo(() => {
    if (mode === 'futuristic') return futuristicTheme;
    return {
      algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    };
  }, [mode]);

  // 未来主义主题时给 html 加作用域类，供补充样式使用
  useEffect(() => {
    document.documentElement.classList.toggle('theme-futuristic', mode === 'futuristic');
  }, [mode]);

  return (
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      {mode === 'futuristic' && <FuturisticBackground />}
      <RouterProvider router={router} />
    </ConfigProvider>
  );
}

export default App;
