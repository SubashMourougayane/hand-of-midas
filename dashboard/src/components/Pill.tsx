import { ReactNode } from "react";

type Tone = "bull" | "bear" | "warn" | "info" | "neutral" | "muted";

const TONE: Record<Tone, string> = {
  bull: "bg-bull/10 text-bull border-bull/30",
  bear: "bg-bear/10 text-bear border-bear/30",
  warn: "bg-warn/10 text-warn border-warn/30",
  info: "bg-info/10 text-info border-info/30",
  neutral: "bg-accent/10 text-accent border-accent/30",
  muted: "bg-bg-elevated text-ink-secondary border-line-base",
};

export function Pill({
  tone = "neutral",
  glow = false,
  children,
  className = "",
}: {
  tone?: Tone;
  glow?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`
        inline-flex items-center gap-1
        px-1.5 py-0.5 rounded-ds-sm border
        text-ds-xs font-medium uppercase tracking-wide
        ${TONE[tone]}
        ${glow && tone === "bull" ? "shadow-ds-glow-bull" : ""}
        ${glow && tone === "bear" ? "shadow-ds-glow-bear" : ""}
        ${className}
      `}
    >
      {children}
    </span>
  );
}
