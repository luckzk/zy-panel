import { useEffect, useRef } from 'react';

/**
 * 未来主义主题背景：模板同款 canvas 粒子场。
 * 移植自 v0 futuristic-dashboard 模板源码（dashboard.tsx）：
 * 根容器为黑 → slate-900 的对角渐变，上方一层 opacity 0.3 的 canvas，
 * 100 个浅蓝白色粒子（1~4px）以 ±0.25px/帧的速度漂移，碰到边缘回绕。
 * 纯装饰层：fixed 全屏、z-index 0、pointer-events none。
 */
const PARTICLE_COUNT = 100;

export default function FuturisticBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvasEl = canvasRef.current;
    if (!canvasEl) return;
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    const canvas: HTMLCanvasElement = canvasEl;

    const fit = () => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    fit();

    // 减弱动态偏好：只画一帧静态粒子，不做动画
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

    interface Particle {
      x: number; y: number; size: number;
      speedX: number; speedY: number; color: string;
      update(): void; draw(): void;
    }

    class Dot implements Particle {
      x = Math.random() * canvas.width;
      y = Math.random() * canvas.height;
      size = Math.random() * 3 + 1;
      speedX = (Math.random() - 0.5) * 0.5;
      speedY = (Math.random() - 0.5) * 0.5;
      color =
        `rgba(${Math.floor(Math.random() * 100) + 100},` +
        `${Math.floor(Math.random() * 100) + 150},` +
        `${Math.floor(Math.random() * 55) + 200},` +
        `${Math.random() * 0.5 + 0.2})`;

      update() {
        this.x += this.speedX;
        this.y += this.speedY;
        if (this.x > canvas.width) this.x = 0;
        if (this.x < 0) this.x = canvas.width;
        if (this.y > canvas.height) this.y = 0;
        if (this.y < 0) this.y = canvas.height;
      }

      draw() {
        if (!ctx) return;
        ctx.fillStyle = this.color;
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    const particles: Particle[] = Array.from({ length: PARTICLE_COUNT }, () => new Dot());

    let raf = 0;
    const render = () => {
      if (!ctx || !canvas) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const p of particles) {
        if (!reduceMotion) p.update();
        p.draw();
      }
      if (!reduceMotion) raf = requestAnimationFrame(render);
    };
    render();

    window.addEventListener('resize', fit);
    return () => {
      window.removeEventListener('resize', fit);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div className="fut-bokeh" aria-hidden>
      <canvas ref={canvasRef} className="fut-bokeh-canvas" />
    </div>
  );
}
