import { useEffect, useRef } from "react";

/**
 * Lightweight canvas gold-particle field (no deps). Ambient gold dust drifts
 * upward; on `burst` a shower of embers explodes from the card centre for the
 * vault-shatter moment. Auto-pauses under prefers-reduced-motion.
 */
type P = {
  x: number; y: number; vx: number; vy: number;
  r: number; life: number; maxLife: number; hue: number;
};

export function GoldParticles({
  burst = 0, // increment to trigger a burst
  density = 40,
  className = "",
}: {
  burst?: number;
  density?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particles = useRef<P[]>([]);
  const raf = useRef<number>(0);
  const burstSeen = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
    };
    resize();
    window.addEventListener("resize", resize);

    // seed ambient dust (index-based, no Math.random at module scope is fine here)
    const rand = (a: number, b: number) => a + Math.random() * (b - a);
    const seed = () => {
      particles.current = Array.from({ length: reduce ? 0 : density }, () => ({
        x: rand(0, canvas.width),
        y: rand(0, canvas.height),
        vx: rand(-0.15, 0.15) * dpr,
        vy: rand(-0.35, -0.08) * dpr,
        r: rand(0.6, 2.0) * dpr,
        life: rand(0, 1),
        maxLife: 1,
        hue: rand(40, 52),
      }));
    };
    seed();

    const spawnBurst = () => {
      const cx = canvas.width / 2;
      const cy = canvas.height / 2;
      for (let i = 0; i < 220; i++) {
        const a = (Math.PI * 2 * i) / 220 + rand(-0.2, 0.2);
        const sp = rand(1.4, 6.5) * dpr; // gentler launch → drifts, not rockets
        particles.current.push({
          x: cx, y: cy,
          vx: Math.cos(a) * sp,
          vy: Math.sin(a) * sp,
          r: rand(1, 3.6) * dpr,
          life: 1, maxLife: 1,
          hue: rand(38, 54),
        });
      }
    };

    const tick = () => {
      if (burstSeen.current !== burst) {
        burstSeen.current = burst;
        if (burst > 0 && !reduce) spawnBurst();
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const list = particles.current;
      for (let i = list.length - 1; i >= 0; i--) {
        const p = list[i];
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.006 * dpr; // softer gravity → embers hang longer
        p.vx *= 0.985; // more drag = slower drift-out
        p.vy *= 0.985;
        // ambient dust wraps; burst embers fade out
        if (p.maxLife === 1 && p.life < 1) {
          // ambient: recycle when off top
          if (p.y < -10) {
            p.y = canvas.height + 10;
            p.x = rand(0, canvas.width);
          }
        }
        p.life -= 0.0022; // slower fade so the gold dust lingers
        const alpha = Math.max(0, Math.min(1, p.life)) * 0.9;
        ctx.beginPath();
        ctx.fillStyle = `hsla(${p.hue}, 85%, 65%, ${alpha})`;
        ctx.shadowBlur = 8 * dpr;
        ctx.shadowColor = `hsla(${p.hue}, 90%, 60%, ${alpha})`;
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
        if (p.life <= 0) {
          // ambient particles respawn; burst embers die
          if (i < density) {
            p.life = 1;
            p.x = rand(0, canvas.width);
            p.y = canvas.height + 10;
            p.vy = rand(-0.35, -0.08) * dpr;
          } else {
            list.splice(i, 1);
          }
        }
      }
      ctx.shadowBlur = 0;
      raf.current = requestAnimationFrame(tick);
    };
    if (!reduce) raf.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf.current);
      window.removeEventListener("resize", resize);
    };
  }, [density, burst]);

  return (
    <canvas
      ref={canvasRef}
      className={`pointer-events-none ${className}`}
      aria-hidden
    />
  );
}
