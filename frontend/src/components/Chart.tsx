import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import { useThemeStore } from '../stores/theme';
import { FUTURISTIC_CHART_COLORS } from '../theme/futuristic';

interface ChartProps {
  option: EChartsOption;
  height?: number;
}

/** ECharts 通用封装：自动跟随主题、窗口缩放自适应、卸载时销毁 */
export default function Chart({ option, height = 320 }: ChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const mode = useThemeStore((s) => s.mode);
  const dark = mode !== 'light';

  // 未来主义主题：默认注入青→绿霓虹配色（页面已显式指定 color 的不受影响）
  const finalOption = useMemo<EChartsOption>(
    () =>
      mode === 'futuristic' && !option.color
        ? { color: FUTURISTIC_CHART_COLORS, ...option }
        : option,
    [option, mode],
  );

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = echarts.init(el, dark ? 'dark' : undefined);
    chart.setOption(finalOption);
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
    };
  }, [finalOption, dark]);

  return <div ref={ref} style={{ width: '100%', height }} />;
}
