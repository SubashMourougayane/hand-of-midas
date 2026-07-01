import { ReactNode } from "react";
import { X } from "lucide-react";

export function ChipGroup({
  label,
  children,
  onClear,
  active,
}: {
  label: string;
  children: ReactNode;
  onClear?: () => void;
  active?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-ds-xs uppercase tracking-wide text-ink-muted shrink-0">
        {label}
      </span>
      <div className="flex items-center gap-1 flex-wrap">{children}</div>
      {onClear && active && (
        <button
          onClick={onClear}
          className="text-ink-muted hover:text-ink-primary p-0.5"
          title={`Clear ${label.toLowerCase()}`}
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}

export function Chip({
  active,
  tone = "neutral",
  onClick,
  count,
  children,
}: {
  active: boolean;
  tone?: "bull" | "bear" | "warn" | "info" | "neutral";
  onClick: () => void;
  count?: number;
  children: ReactNode;
}) {
  const toneCls = active
    ? tone === "bull"
      ? "bg-bull/15 text-bull border-bull/40"
      : tone === "bear"
      ? "bg-bear/15 text-bear border-bear/40"
      : tone === "warn"
      ? "bg-warn/15 text-warn border-warn/40"
      : tone === "info"
      ? "bg-info/15 text-info border-info/40"
      : "bg-brass/15 text-brass-hi border-brass/40"
    : "bg-bg-elevated text-ink-muted border-line-base hover:text-ink-secondary hover:border-line-strong";
  return (
    <button
      onClick={onClick}
      className={`
        inline-flex items-center gap-1.5
        px-2 py-0.5 rounded-ds-sm border
        text-ds-xs font-medium
        transition-colors duration-ds
        ${toneCls}
      `}
    >
      <span>{children}</span>
      {count != null && (
        <span className="text-[10px] opacity-70 font-mono">
          {count.toLocaleString()}
        </span>
      )}
    </button>
  );
}
