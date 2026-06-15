"use client";
import { ReactNode } from "react";
import { cn } from "./cn";
import { Display } from "./Display";

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  className?: string;
  /** Render the title in serif Display font (default true). Pass false for
   *  pages where the page title sits next to a system context badge. */
  serif?: boolean;
  /** Display size for serif headlines. Default "md" (32px) */
  size?: "sm" | "md" | "lg" | "xl";
}

export function PageHeader({
  title,
  description,
  breadcrumb,
  actions,
  className,
  serif = true,
  size = "md",
}: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-1 mb-5 hom-fade-in-up", className)}>
      {breadcrumb ? (
        <div className="text-[11.5px] font-medium text-[var(--color-text-dim)] uppercase tracking-[1.4px]">
          {breadcrumb}
        </div>
      ) : null}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex flex-col gap-2">
          {serif ? (
            <Display size={size} italic className="leading-none">{title}</Display>
          ) : (
            <h1 className="text-[22px] font-semibold text-[var(--color-text)] leading-tight">
              {title}
            </h1>
          )}
          {description ? (
            <p className="text-[14.5px] text-[var(--color-text-dim)] leading-relaxed">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2 mt-1">{actions}</div> : null}
      </div>
      <div className="hom-rule mt-3" />
    </header>
  );
}
