import { ReactNode } from "react";

export function Tabs({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-0 border-b border-line-subtle">
      {children}
    </div>
  );
}

export function Tab({
  active,
  onClick,
  children,
  badge,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`
        relative px-3 py-2 text-ds-sm font-medium
        transition-colors duration-ds
        ${active ? "text-ink-primary" : "text-ink-muted hover:text-ink-secondary"}
      `}
    >
      <span className="inline-flex items-center gap-1.5">
        {children}
        {badge && (
          <span className="text-ds-xs text-ink-muted">{badge}</span>
        )}
      </span>
      {active && (
        <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-bull rounded-t-sm" />
      )}
    </button>
  );
}
