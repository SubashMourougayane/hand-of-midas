"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "./cn";

type Point = { y: number; e: number; yr_pnl?: number };

interface EquityCurveProps {
  data: Point[];
  height?: number;
  className?: string;
  /** Re-trigger draw animation when this key changes (e.g. system tab) */
  triggerKey?: string;
}

/**
 * Smooth, animated cumulative-P&L curve. Apple-grade chart:
 * - Catmull-Rom-smoothed path (no ECG spikes from straight segments)
 * - Brass gradient stroke + shaded area underneath
 * - Strokes in left→right via stroke-dashoffset on triggerKey change
 * - Axis labels stagger-fade in after path completes
 * - Hover crosshair with cushioned tooltip
 *
 * Scales responsively to its parent's width via ResizeObserver.
 */
export function EquityCurve({
  data,
  height = 280,
  className,
  triggerKey = "default",
}: EquityCurveProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const pathRef = useRef<SVGPathElement>(null);
  const [w, setW] = useState(900);
  const [progress, setProgress] = useState(0);
  const [pathLen, setPathLen] = useState(0);
  const [hovered, setHovered] = useState<{
    x: number;
    y: number;
    point: Point;
    idx: number;
  } | null>(null);

  // Responsive width
  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver(() => {
      const cw = wrapRef.current?.clientWidth ?? 900;
      setW(cw);
    });
    ro.observe(wrapRef.current);
    setW(wrapRef.current.clientWidth);
    return () => ro.disconnect();
  }, []);

  // Animation: rerun on triggerKey change
  useEffect(() => {
    setProgress(0);
    const start = performance.now();
    const duration = 1400;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      // ease-out-quart for confident-but-deliberate draw
      const eased = 1 - Math.pow(1 - t, 4);
      setProgress(eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [triggerKey]);

  // Compute path length once mounted
  useEffect(() => {
    if (pathRef.current) setPathLen(pathRef.current.getTotalLength());
  }, [w, data]);

  if (!data || data.length === 0) return <div style={{ height }} />;

  const pad = { l: 56, r: 24, t: 24, b: 36 };
  const h = height;
  const cw = Math.max(1, w - pad.l - pad.r);
  const ch = h - pad.t - pad.b;

  // Domain
  const minE = Math.min(0, ...data.map((p) => p.e));
  const maxE = Math.max(...data.map((p) => p.e));
  const eRange = maxE - minE || 1;

  const xAt = (i: number) => pad.l + (i / Math.max(1, data.length - 1)) * cw;
  const yAt = (e: number) => pad.t + ch - ((e - minE) / eRange) * ch;

  // Catmull-Rom → bezier conversion (alpha=0.5 = centripetal, no overshoot)
  const smoothPath = useMemo(() => {
    if (data.length < 2) return "";
    const pts = data.map((p, i) => [xAt(i), yAt(p.e)] as [number, number]);
    const result: string[] = [`M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`];
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[i + 2] || p2;
      const tension = 0.5; // smoothing
      const cp1x = p1[0] + (p2[0] - p0[0]) / 6 * tension * 2;
      const cp1y = p1[1] + (p2[1] - p0[1]) / 6 * tension * 2;
      const cp2x = p2[0] - (p3[0] - p1[0]) / 6 * tension * 2;
      const cp2y = p2[1] - (p3[1] - p1[1]) / 6 * tension * 2;
      result.push(`C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)} ${cp2x.toFixed(2)} ${cp2y.toFixed(2)} ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`);
    }
    return result.join(" ");
  }, [data, w, h]);

  const fillPath = useMemo(() => {
    if (!smoothPath) return "";
    return `${smoothPath} L ${xAt(data.length - 1).toFixed(2)} ${pad.t + ch} L ${xAt(0).toFixed(2)} ${pad.t + ch} Z`;
  }, [smoothPath, data, w, h]);

  const dashOffset = pathLen * (1 - progress);

  // Y-axis ticks: 4 evenly-spaced values
  const yTicks = [minE, minE + eRange * 0.33, minE + eRange * 0.66, maxE];

  // X-axis labels: ~6 year ticks
  const xTickStep = Math.max(1, Math.ceil(data.length / 6));
  const xTicks = data.filter((_, i) => i % xTickStep === 0 || i === data.length - 1);

  const fmtMoney = (v: number) => {
    const abs = Math.abs(v);
    const sign = v < 0 ? "-" : "";
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `${sign}$${Math.round(abs / 1e3)}k`;
    return `${sign}$${Math.round(abs)}`;
  };

  // Hover handler
  const handleMove = (e: React.MouseEvent<SVGElement>) => {
    if (!wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    if (mx < pad.l || mx > pad.l + cw) {
      setHovered(null);
      return;
    }
    const i = Math.round(((mx - pad.l) / cw) * (data.length - 1));
    if (i < 0 || i >= data.length) return;
    setHovered({ x: xAt(i), y: yAt(data[i].e), point: data[i], idx: i });
  };

  return (
    <div ref={wrapRef} className={cn("relative w-full select-none", className)}>
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        onMouseMove={handleMove}
        onMouseLeave={() => setHovered(null)}
        style={{ display: "block", overflow: "visible" }}
      >
        <defs>
          <linearGradient id="eq-stroke" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#047857" />
            <stop offset="50%" stopColor="#10b981" />
            <stop offset="100%" stopColor="#34d399" />
          </linearGradient>
          <linearGradient id="eq-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
            <stop offset="60%" stopColor="#10b981" stopOpacity="0.06" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
          </linearGradient>
          <filter id="eq-glow">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Y-axis grid + labels */}
        {yTicks.map((v, i) => (
          <g key={i} style={{ opacity: Math.max(0, progress - 0.4) * 1.6 }}>
            <line
              x1={pad.l}
              x2={pad.l + cw}
              y1={yAt(v)}
              y2={yAt(v)}
              stroke="#252a35"
              strokeWidth={0.5}
              strokeDasharray={i === 0 ? undefined : "1,4"}
            />
            <text
              x={pad.l - 10}
              y={yAt(v) + 3}
              fontSize={10}
              fill="#6e7585"
              textAnchor="end"
              fontFamily="var(--font-mono)"
              letterSpacing="0.02em"
            >
              {fmtMoney(v)}
            </text>
          </g>
        ))}

        {/* X-axis labels */}
        {xTicks.map((p, i) => {
          const idx = data.indexOf(p);
          return (
            <text
              key={p.y}
              x={xAt(idx)}
              y={h - 10}
              fontSize={10}
              fill="#6e7585"
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              style={{
                opacity: Math.max(0, progress - 0.5) * 2,
                transition: "opacity 200ms",
              }}
            >
              ’{String(p.y).slice(2)}
            </text>
          );
        })}

        {/* Filled area under curve */}
        <path
          d={fillPath}
          fill="url(#eq-fill)"
          style={{
            opacity: progress * 0.95,
            transition: "opacity 200ms",
          }}
        />

        {/* Stroke line — animated draw via dashoffset */}
        <path
          ref={pathRef}
          d={smoothPath}
          fill="none"
          stroke="url(#eq-stroke)"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={pathLen || undefined}
          strokeDashoffset={dashOffset}
          filter="url(#eq-glow)"
        />

        {/* Endpoint marker — appears once draw completes */}
        {progress > 0.95 && data.length > 0 && (
          <g
            style={{
              opacity: (progress - 0.95) * 20,
              transition: "opacity 250ms",
            }}
          >
            <circle
              cx={xAt(data.length - 1)}
              cy={yAt(data[data.length - 1].e)}
              r={6}
              fill="#10b981"
              opacity={0.25}
            >
              <animate
                attributeName="r"
                values="6;10;6"
                dur="2.4s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="opacity"
                values="0.25;0;0.25"
                dur="2.4s"
                repeatCount="indefinite"
              />
            </circle>
            <circle
              cx={xAt(data.length - 1)}
              cy={yAt(data[data.length - 1].e)}
              r={3}
              fill="#10b981"
              stroke="#0c0a08"
              strokeWidth={1}
            />
          </g>
        )}

        {/* Hover crosshair */}
        {hovered && (
          <g pointerEvents="none">
            <line
              x1={hovered.x}
              x2={hovered.x}
              y1={pad.t}
              y2={pad.t + ch}
              stroke="#10b981"
              strokeWidth={0.75}
              strokeDasharray="3,3"
              opacity={0.5}
            />
            <circle
              cx={hovered.x}
              cy={hovered.y}
              r={5}
              fill="#10b981"
              stroke="#0c0a08"
              strokeWidth={2}
            />
          </g>
        )}
      </svg>

      {/* Hover tooltip — HTML overlay for crisper text */}
      {hovered && (
        <div
          className="pointer-events-none absolute z-10 rounded-none border border-[var(--color-brass)]/40 bg-[var(--color-surface-2)]/95 px-3 py-2 text-[11px] shadow-xl backdrop-blur"
          style={{
            left: Math.min(hovered.x + 14, w - 130),
            top: hovered.y - 50,
            fontFamily: "var(--font-mono)",
            transition: "left 80ms ease-out, top 80ms ease-out",
          }}
        >
          <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-muted)]">
            {hovered.point.y}
          </div>
          <div className="mt-0.5 text-[13px] font-bold text-[var(--color-brass)]">
            {fmtMoney(hovered.point.e)}
          </div>
          {typeof hovered.point.yr_pnl === "number" && hovered.point.yr_pnl !== 0 && (
            <div className="mt-0.5 text-[10px]">
              <span className="text-[var(--color-text-muted)]">year: </span>
              <span
                style={{
                  color:
                    hovered.point.yr_pnl >= 0
                      ? "var(--color-win)"
                      : "var(--color-loss)",
                }}
              >
                {hovered.point.yr_pnl >= 0 ? "+" : ""}
                {fmtMoney(hovered.point.yr_pnl)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
