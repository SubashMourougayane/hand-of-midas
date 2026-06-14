"use client";
import { cn } from "./cn";

type Tone = "win" | "loss" | "info" | "warn" | "muted";

interface StatusDotProps {
  tone?: Tone;
  pulse?: boolean;
  size?: number;
  className?: string;
}

const COLOR: Record<Tone, string> = {
  win: "bg-[var(--color-win)]",
  loss: "bg-[var(--color-loss)]",
  info: "bg-[var(--color-info)]",
  warn: "bg-[var(--color-warn)]",
  muted: "bg-[var(--color-text-muted)]",
};

export function StatusDot({ tone = "info", pulse = false, size = 8, className }: StatusDotProps) {
  return (
    <span
      style={{ width: size, height: size }}
      className={cn(
        "inline-block rounded-full relative flex-shrink-0",
        COLOR[tone],
        className,
      )}
      aria-hidden
    >
      {pulse ? (
        <span
          className={cn(
            "absolute inset-0 rounded-full opacity-75 animate-ping",
            COLOR[tone],
          )}
          aria-hidden
        />
      ) : null}
    </span>
  );
}
