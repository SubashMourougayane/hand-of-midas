"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center gap-2 px-4 py-8",
        className,
      )}
    >
      {icon ? <div className="text-[var(--color-text-muted)] mb-1">{icon}</div> : null}
      <p className="text-[13px] font-medium text-[var(--color-text)]">{title}</p>
      {description ? (
        <p className="text-[13.5px] text-[var(--color-text-dim)] max-w-xs leading-relaxed">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
