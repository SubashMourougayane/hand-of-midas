"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  description,
  breadcrumb,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-1 mb-4", className)}>
      {breadcrumb ? (
        <div className="text-[11px] text-[var(--color-text-muted)] uppercase tracking-[0.6px]">
          {breadcrumb}
        </div>
      ) : null}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-[20px] font-semibold text-[var(--color-text)] leading-tight">
            {title}
          </h1>
          {description ? (
            <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
