"use client";
import { HTMLAttributes } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "win" | "loss" | "info" | "warn" | "system";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  variant?: "solid" | "soft" | "outline";
  systemColor?: string;
}

const TONE: Record<Exclude<Tone, "system">, { solid: string; soft: string; outline: string }> = {
  neutral: {
    solid: "bg-[var(--color-surface-3)] text-[var(--color-text)] border-[var(--color-border-hi)]",
    soft: "bg-[var(--color-surface-2)] text-[var(--color-text-dim)] border-[var(--color-border)]",
    outline: "bg-transparent text-[var(--color-text-dim)] border-[var(--color-border)]",
  },
  win: {
    solid: "bg-[var(--color-win)] text-black border-[var(--color-win)]",
    soft: "bg-[var(--color-win)]/12 text-[var(--color-win)] border-[var(--color-win)]/30",
    outline: "bg-transparent text-[var(--color-win)] border-[var(--color-win)]/60",
  },
  loss: {
    solid: "bg-[var(--color-loss)] text-black border-[var(--color-loss)]",
    soft: "bg-[var(--color-loss)]/12 text-[var(--color-loss)] border-[var(--color-loss)]/30",
    outline: "bg-transparent text-[var(--color-loss)] border-[var(--color-loss)]/60",
  },
  info: {
    solid: "bg-[var(--color-info)] text-black border-[var(--color-info)]",
    soft: "bg-[var(--color-info)]/12 text-[var(--color-info)] border-[var(--color-info)]/30",
    outline: "bg-transparent text-[var(--color-info)] border-[var(--color-info)]/60",
  },
  warn: {
    solid: "bg-[var(--color-warn)] text-black border-[var(--color-warn)]",
    soft: "bg-[var(--color-warn)]/12 text-[var(--color-warn)] border-[var(--color-warn)]/30",
    outline: "bg-transparent text-[var(--color-warn)] border-[var(--color-warn)]/60",
  },
};

export function Badge({
  tone = "neutral",
  variant = "soft",
  systemColor,
  className,
  style,
  children,
  ...rest
}: BadgeProps) {
  const isSystem = tone === "system" && systemColor;
  const systemStyle = isSystem
    ? {
        color: systemColor,
        borderColor: `${systemColor}80`,
        backgroundColor: `${systemColor}1f`,
      }
    : undefined;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 border rounded-[4px]",
        "text-[10px] font-semibold uppercase tracking-[0.6px] leading-none",
        !isSystem && TONE[tone as Exclude<Tone, "system">][variant],
        className,
      )}
      style={{ ...systemStyle, ...style }}
      {...rest}
    >
      {children}
    </span>
  );
}
