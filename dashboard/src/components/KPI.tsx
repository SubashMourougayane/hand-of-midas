import { ReactNode } from "react";

export function KPI({
  label,
  value,
  delta,
  deltaTone = "neutral",
  sub,
  loading = false,
}: {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  deltaTone?: "bull" | "bear" | "neutral";
  sub?: ReactNode;
  loading?: boolean;
}) {
  const deltaCls =
    deltaTone === "bull"
      ? "text-bull"
      : deltaTone === "bear"
      ? "text-bear"
      : "text-ink-muted";

  return (
    <div className="bg-bg-surface border border-line-subtle rounded-ds px-3 py-2.5 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
          {label}
        </span>
        {delta && (
          <span className={`text-ds-xs font-mono font-medium ${deltaCls}`}>
            {delta}
          </span>
        )}
      </div>
      <div className="mt-1 text-ds-2xl font-semibold text-ink-primary font-mono leading-tight truncate">
        {loading ? <span className="inline-block w-24 h-7 ds-skeleton rounded" /> : value}
      </div>
      {sub && (
        <div className="mt-0.5 text-ds-xs text-ink-secondary truncate">{sub}</div>
      )}
    </div>
  );
}
