"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "win" | "loss" | "info" | "warn" | "muted";

interface StatProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  trend?: "up" | "down" | "flat";
  size?: "sm" | "md" | "lg";
  mono?: boolean;
  className?: string;
}

const TONE_COLOR: Record<Tone, string> = {
  neutral: "text-[var(--color-text)]",
  win: "text-[var(--color-win)]",
  loss: "text-[var(--color-loss)]",
  info: "text-[var(--color-info)]",
  warn: "text-[var(--color-warn)]",
  muted: "text-[var(--color-text-muted)]",
};

const SIZE: Record<NonNullable<StatProps["size"]>, { value: string; label: string }> = {
  sm: { value: "text-[16px]", label: "text-[10px]" },
  md: { value: "text-[20px]", label: "text-[11px]" },
  lg: { value: "text-[28px]", label: "text-[11px]" },
};

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  trend,
  size = "md",
  mono = true,
  className,
}: StatProps) {
  const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : trend === "flat" ? "·" : "";
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <span
        className={cn(
          "uppercase tracking-[0.6px] text-[var(--color-text-muted)] font-medium",
          SIZE[size].label,
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "font-semibold leading-tight",
          mono && "num",
          TONE_COLOR[tone],
          SIZE[size].value,
        )}
      >
        {arrow ? <span className="mr-1 text-[0.7em]">{arrow}</span> : null}
        {value}
      </span>
      {hint != null ? (
        <span className="text-[11px] text-[var(--color-text-muted)] leading-tight">{hint}</span>
      ) : null}
    </div>
  );
}
