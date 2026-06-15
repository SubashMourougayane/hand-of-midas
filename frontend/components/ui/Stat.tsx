"use client";
import { ReactNode } from "react";
import { cn } from "./cn";
import { CountUp } from "./CountUp";

type Tone = "neutral" | "win" | "loss" | "info" | "warn" | "muted" | "brass";

interface StatProps {
  label: string;
  /** Either a ReactNode (rendered as-is) or a number (animated via CountUp when `animate`). */
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  trend?: "up" | "down" | "flat";
  size?: "sm" | "md" | "lg";
  /** Apply mono+tabular-nums to the value. Default true. */
  mono?: boolean;
  /** When `value` is a number, animate from prior value via CountUp. Default false. */
  animate?: boolean;
  /** CountUp formatting (only when `value` is number + `animate` true). */
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

const TONE_COLOR: Record<Tone, string> = {
  neutral: "text-[var(--color-text)]",
  win: "text-[var(--color-win)]",
  loss: "text-[var(--color-loss)]",
  info: "text-[var(--color-info)]",
  warn: "text-[var(--color-warn)]",
  muted: "text-[var(--color-text-muted)]",
  brass: "text-[var(--color-brass-hi)]",
};

const SIZE: Record<NonNullable<StatProps["size"]>, { value: string; label: string }> = {
  sm: { value: "text-[17px]", label: "text-[11.5px]" },
  md: { value: "text-[22px]", label: "text-[11.5px]" },
  lg: { value: "text-[30px]", label: "text-[11.5px]" },
};

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  trend,
  size = "md",
  mono = true,
  animate = false,
  decimals = 0,
  prefix = "",
  suffix = "",
  className,
}: StatProps) {
  const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : trend === "flat" ? "·" : "";
  const isNumber = typeof value === "number";
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span
        className={cn(
          "uppercase tracking-[1.4px] text-[var(--color-text-dim)] font-medium",
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
        {arrow ? <span className="mr-1 text-[0.7em] opacity-90">{arrow}</span> : null}
        {animate && isNumber ? (
          <CountUp value={value} decimals={decimals} prefix={prefix} suffix={suffix} />
        ) : (
          value
        )}
      </span>
      {hint != null ? (
        <span className="text-[12.5px] text-[var(--color-text-dim)] leading-tight">{hint}</span>
      ) : null}
    </div>
  );
}
