"use client";
import { forwardRef, HTMLAttributes } from "react";
import { cn } from "./cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  surface?: 1 | 2 | 3;
  bordered?: boolean;
  padded?: boolean;
  /** Apply hover-lift animation (translateY -1px + brass border tint). */
  lift?: boolean;
}

const SURFACE: Record<1 | 2 | 3, string> = {
  1: "bg-[var(--color-surface-1)]",
  2: "bg-[var(--color-surface-2)]",
  3: "bg-[var(--color-surface-3)]",
};

const CardRoot = forwardRef<HTMLDivElement, CardProps>(function Card(
  { surface = 1, bordered = true, padded = false, lift = false, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "rounded-[5px]",
        SURFACE[surface],
        bordered && "border border-[var(--color-border)]",
        padded && "p-4",
        lift && "hom-lift",
        className,
      )}
      {...rest}
    />
  );
});

const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function CardHeader(
  { className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "flex items-center justify-between gap-3 px-4 py-2.5",
        "border-b border-[var(--color-border)]",
        className,
      )}
      {...rest}
    />
  );
});

const CardTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(function CardTitle(
  { className, ...rest },
  ref,
) {
  return (
    <h3
      ref={ref}
      className={cn(
        "text-[11px] font-semibold uppercase tracking-[0.8px] text-[var(--color-text-dim)]",
        className,
      )}
      {...rest}
    />
  );
});

const CardBody = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function CardBody(
  { className, ...rest },
  ref,
) {
  return <div ref={ref} className={cn("p-4", className)} {...rest} />;
});

const CardFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function CardFooter(
  { className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "flex items-center justify-end gap-2 px-4 py-2.5 border-t border-[var(--color-border)]",
        className,
      )}
      {...rest}
    />
  );
});

export const Card = Object.assign(CardRoot, {
  Header: CardHeader,
  Title: CardTitle,
  Body: CardBody,
  Footer: CardFooter,
});
