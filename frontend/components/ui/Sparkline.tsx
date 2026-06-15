"use client";

interface SparklineProps {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fillOpacity?: number;
  className?: string;
}

/**
 * Lightweight inline-SVG sparkline. Avoids loading recharts for tiny visuals.
 * Auto-scales to its data range. Renders stroke + optional fill.
 */
export function Sparkline({
  values,
  width = 60,
  height = 20,
  color = "var(--color-info)",
  fillOpacity = 0.18,
  className,
}: SparklineProps) {
  if (values.length < 2) {
    return (
      <svg width={width} height={height} className={className} aria-hidden>
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke="var(--color-border)"
          strokeWidth={1}
        />
      </svg>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / span) * height;
    return [x, y] as const;
  });
  const linePath = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const areaPath = `${linePath} L${width.toFixed(2)},${height} L0,${height} Z`;
  const last = values[values.length - 1];
  const first = values[0];
  const dir = last >= first ? "up" : "down";

  return (
    <svg width={width} height={height} className={className} aria-hidden data-trend={dir}>
      <path d={areaPath} fill={color} opacity={fillOpacity} />
      <path d={linePath} fill="none" stroke={color} strokeWidth={1.25} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
