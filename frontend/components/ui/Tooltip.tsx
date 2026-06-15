"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

interface TooltipProps {
  content: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactNode;
  className?: string;
}

const SIDE: Record<NonNullable<TooltipProps["side"]>, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
  left: "right-full top-1/2 -translate-y-1/2 mr-1.5",
  right: "left-full top-1/2 -translate-y-1/2 ml-1.5",
};

export function Tooltip({ content, side = "top", children, className }: TooltipProps) {
  return (
    <span className={cn("relative inline-flex group", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "absolute z-50 pointer-events-none",
          "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
          "transition-opacity delay-100 duration-150",
          "px-2 py-1 rounded-[4px] text-[11px] whitespace-nowrap",
          "bg-[var(--color-surface-3)] text-[var(--color-text)] border border-[var(--color-border-hi)] shadow-lg",
          SIDE[side],
        )}
      >
        {content}
      </span>
    </span>
  );
}
