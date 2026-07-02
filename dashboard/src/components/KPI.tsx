import { ReactNode } from "react";

export function KPI({
  label,
  value,
  delta,
  deltaTone = "neutral",
  sub,
  spark,
  accent = "lime",
  loading = false,
}: {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  deltaTone?: "bull" | "bear" | "neutral";
  sub?: ReactNode;
  /** optional mini sparkline series (rendered as a glowing underline chart) */
  spark?: number[];
  /** glow accent for the sparkline / card edge */
  accent?: "lime" | "cyan" | "bull" | "bear" | "magenta";
  loading?: boolean;
}) {
  const chip =
    deltaTone === "bull"
      ? "text-bull bg-bull/10 border-bull/30"
      : deltaTone === "bear"
      ? "text-bear bg-bear/10 border-bear/30"
      : "text-ink-muted bg-bg-elevated border-line-base";

  const strokeFor: Record<string, string> = {
    lime: "#e8eaed",
    cyan: "#c3c7cd",
    bull: "#22c55e",
    bear: "#f04452",
    magenta: "#c3c7cd",
  };

  return (
    <div className="group relative glass rounded-ds-lg px-4 py-3.5 min-w-0 overflow-hidden transition-all duration-ds hover:shadow-ds-hover">
      <div className="flex items-start justify-between gap-2">
        <span className="text-ds-xs uppercase tracking-[0.14em] text-ink-muted">
          {label}
        </span>
        {delta && (
          <span
            className={`text-ds-xs font-mono font-semibold px-1.5 py-0.5 rounded-full border ${chip}`}
          >
            {delta}
          </span>
        )}
      </div>
      <div className="mt-2 text-ds-2xl font-bold text-ink-primary font-mono leading-tight truncate">
        {loading ? <span className="inline-block w-24 h-7 ds-skeleton rounded" /> : value}
      </div>
      {sub && (
        <div className="mt-0.5 text-ds-xs text-ink-muted truncate">{sub}</div>
      )}
      {spark && spark.length > 1 && (
        <Sparkline data={spark} stroke={strokeFor[accent] ?? "#BBF351"} />
      )}
    </div>
  );
}

/** Tiny glowing sparkline — decorative trend under a KPI value. */
function Sparkline({ data, stroke }: { data: number[]; stroke: string }) {
  const w = 120;
  const h = 26;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const step = w / (data.length - 1);
  const pts = data
    .map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      className="mt-2.5 w-full"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      height={h}
      aria-hidden
    >
      <polyline
        points={pts}
        fill="none"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 4px ${stroke})` }}
      />
    </svg>
  );
}
