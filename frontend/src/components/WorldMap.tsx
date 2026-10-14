import { useMemo } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import Chart from './Chart';
import { useThemeStore } from '../stores/theme';
import type { IpMapPoint } from '../api/ipinfo';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import worldJson from '../assets/world.json';

type MapInput = Parameters<typeof echarts.registerMap>[1];
echarts.registerMap('world', worldJson as unknown as MapInput);

/** 全球实例分布图：世界地图 + effectScatter 涟漪打点 */
export default function WorldMap({ points }: { points: IpMapPoint[] }) {
  const mode = useThemeStore((s) => s.mode);
  const dark = mode !== 'light';
  const futuristic = mode === 'futuristic';

  const option = useMemo<EChartsOption>(() => {
    const areaColor = futuristic ? '#0d1420' : dark ? '#151b28' : '#e9eff6';
    const borderColor = futuristic
      ? 'rgba(0, 229, 127, 0.25)'
      : dark
        ? 'rgba(148, 163, 184, 0.25)'
        : '#b9c6d8';
    const dotColor = futuristic ? '#00e57f' : '#2f6df6';
    return {
      tooltip: {
        trigger: 'item',
        backgroundColor: dark ? '#161a23' : '#fff',
        borderColor: borderColor,
        textStyle: { color: dark ? '#eef2f7' : '#333', fontSize: 12 },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        formatter: (p: any) => {
          const d = p.data as IpMapPoint & { value: number[] };
          if (!d || !d.ip) return '';
          const loc = [d.city, d.country].filter(Boolean).join(' · ');
          return (
            `<div style="font-weight:600;margin-bottom:4px">${d.instance_name || '(未命名实例)'}</div>` +
            `<div>租户：${d.tenant_name}</div>` +
            `<div>IP：${d.ip}</div>` +
            (loc ? `<div>位置：${loc}</div>` : '') +
            (d.isp ? `<div>ISP：${d.isp}</div>` : '')
          );
        },
      },
      geo: {
        map: 'world',
        roam: true,
        scaleLimit: { min: 1, max: 8 },
        label: { show: false },
        itemStyle: { areaColor, borderColor },
        emphasis: {
          label: { show: false },
          itemStyle: { areaColor: futuristic ? '#12241a' : dark ? '#1e2739' : '#d7e3f2' },
        },
      },
      series: [
        {
          type: 'effectScatter',
          coordinateSystem: 'geo',
          data: points.map((p) => ({ ...p, name: p.instance_name, value: [p.lon, p.lat] })),
          symbolSize: 9,
          rippleEffect: { brushType: 'stroke', scale: 4.5 },
          itemStyle: { color: dotColor, shadowBlur: 12, shadowColor: dotColor },
          label: { show: false },
          emphasis: { scale: 1.4 },
        },
      ],
    };
  }, [points, dark, futuristic]);

  return <Chart option={option} height={380} />;
}
