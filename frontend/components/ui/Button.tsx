"use client";
import { forwardRef, ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-[var(--color-win)] text-black border border-[var(--color-win)] " +
    "hover:bg-[#1ec870] hover:border-[#1ec870] " +
    "focus-visible:ring-2 focus-visible:ring-[var(--color-win)]/40",
  secondary:
    "bg-[var(--color-surface-1)] text-[var(--color-text)] border border-[var(--color-border)] " +
    "hover:bg-[var(--color-surface-2)] hover:border-[var(--color-border-hi)] " +
    "focus-visible:ring-2 focus-visible:ring-[var(--color-border-hi)]/60",
  ghost:
    "bg-transparent text-[var(--color-text-dim)] border border-transparent " +
    "hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)] " +
    "focus-visible:ring-2 focus-visible:ring-[var(--color-border-hi)]/60",
  destructive:
    "bg-[var(--color-loss)]/10 text-[var(--color-loss)] border border-[var(--color-loss)]/40 " +
    "hover:bg-[var(--color-loss)]/15 hover:border-[var(--color-loss)] " +
    "focus-visible:ring-2 focus-visible:ring-[var(--color-loss)]/40",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 text-[11px] rounded-[4px]",
  md: "h-8 px-3 text-[12px] rounded-[6px]",
  lg: "h-10 px-4 text-[13px] rounded-[6px]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      data-loading={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 font-medium tracking-tight",
        "transition-colors outline-none focus-visible:outline-none",
        "disabled:opacity-40 disabled:cursor-not-allowed",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <span className="inline-block w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin" /> : null}
      {children}
    </button>
  );
});
