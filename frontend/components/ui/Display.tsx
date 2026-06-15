"use client";
import { ReactNode, ElementType } from "react";
import { cn } from "./cn";

interface DisplayProps {
  children: ReactNode;
  as?: ElementType;
  size?: "sm" | "md" | "lg" | "xl";
  italic?: boolean;
  className?: string;
}

const SIZE: Record<NonNullable<DisplayProps["size"]>, string> = {
  sm: "text-[24px]",
  md: "text-[32px]",
  lg: "text-[44px]",
  xl: "text-[56px] md:text-[72px]",
};

/**
 * Serif display heading — Instrument Serif via .display class. Use for
 * page titles ("Trades", "Live"), hero copy, marquee numbers. Reserves the
 * type face for narrative moments rather than every label.
 */
export function Display({
  children,
  as: Tag = "h1",
  size = "md",
  italic = false,
  className,
}: DisplayProps) {
  return (
    <Tag
      className={cn(
        "display text-[var(--color-text)]",
        SIZE[size],
        italic && "italic",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
