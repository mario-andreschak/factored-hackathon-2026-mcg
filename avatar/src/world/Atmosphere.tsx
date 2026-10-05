import { useEffect, useRef } from 'react';

type Props = { weather: 'rain' | 'fireflies' | 'pollen'; reducedMotion: boolean; audioLevel: number };

/** A single lightweight layer gives the paintings a living atmosphere. */
export default function Atmosphere({ weather, reducedMotion, audioLevel }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const level = useRef(audioLevel);
  level.current = audioLevel;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    let width = 0;
    let height = 0;
    let request = 0;
    let stopped = false;
    let last = 0;
    let elapsed = 0;
    const particles = Array.from({ length: weather === 'rain' ? 95 : 38 }, (_, index) => ({
      x: ((index * 37 + 13) % 101) / 101,
      y: ((index * 53 + 41) % 107) / 107,
      phase: index * 2.39996,
      radius: 0.75 + (index % 4) * 0.48,
      speed: 0.08 + (index % 7) * 0.025,
    }));
    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      width = bounds.width;
      height = bounds.height;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw(performance.now());
    };
    const draw = (now: number) => {
      const delta = last ? Math.min((now - last) / 1000, 0.05) : 0;
      last = now;
      if (!reducedMotion) elapsed += delta;
      context.clearRect(0, 0, width, height);
      for (const particle of particles) {
        const pulse = 0.28 + (Math.sin(elapsed * 0.75 + particle.phase) + 1) * 0.22;
        if (weather === 'rain') {
          const x = (particle.x * width - elapsed * 27 * particle.speed + width) % width;
          const y = ((particle.y * height + elapsed * 640 * particle.speed) % (height + 30)) - 30;
          context.strokeStyle = 'rgba(182,214,235,0.18)';
          context.lineWidth = 0.8;
          context.beginPath();
          context.moveTo(x, y);
          context.lineTo(x - 3, y + 16 + particle.radius * 3);
          context.stroke();
        } else {
          const x = particle.x * width + Math.sin(elapsed * particle.speed + particle.phase) * 35;
          const y = particle.y * height + Math.cos(elapsed * particle.speed * 0.65 + particle.phase) * 25;
          const glow = weather === 'fireflies';
          context.fillStyle = glow ? `rgba(255,224,137,${pulse})` : `rgba(248,238,214,${pulse * 0.42})`;
          context.shadowColor = '#ffcb70';
          context.shadowBlur = glow ? 12 + level.current * 8 : 0;
          context.beginPath();
          context.arc(x, y, particle.radius + (glow ? level.current * 0.7 : 0), 0, Math.PI * 2);
          context.fill();
        }
      }
      context.shadowBlur = 0;
    };
    const loop = (now: number) => {
      if (stopped || document.hidden) return;
      draw(now);
      if (!reducedMotion) request = requestAnimationFrame(loop);
    };
    const visibility = () => {
      cancelAnimationFrame(request);
      last = 0;
      if (!document.hidden) request = requestAnimationFrame(loop);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    document.addEventListener('visibilitychange', visibility);
    request = requestAnimationFrame(loop);
    return () => {
      stopped = true;
      cancelAnimationFrame(request);
      observer.disconnect();
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [weather, reducedMotion]);

  return <canvas ref={ref} className="world-atmosphere" aria-hidden="true" />;
}
