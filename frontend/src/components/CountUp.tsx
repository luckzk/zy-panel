import { useEffect, useRef, useState } from 'react';

interface CountUpProps {
  /** 目标数值 */
  value: number;
  /** 动画时长（毫秒） */
  duration?: number;
  /** 格式化显示值，默认取整 */
  format?: (v: number) => string;
}

/** 数字滚动：挂载或数值变化时从旧值 tween 到目标值（模板里的动态数字感） */
export default function CountUp({ value, duration = 900, format }: CountUpProps) {
  const [display, setDisplay] = useState(0);
  const fromRef = useRef(0);
  const rafRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    const to = Number.isFinite(value) ? value : 0;
    if (from === to) {
      setDisplay(to);
      return;
    }
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      const v = from + (to - from) * eased;
      setDisplay(v);
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafRef.current);
      fromRef.current = to;
    };
  }, [value, duration]);

  return <>{format ? format(display) : Math.round(display)}</>;
}
