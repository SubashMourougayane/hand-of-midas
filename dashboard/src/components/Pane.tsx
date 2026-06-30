import { ReactNode } from "react";

export function Pane({
  title,
  right,
  children,
  className = "",
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`border border-term-amber flex flex-col min-h-0 ${className}`}>
      <div className="flex items-center justify-between border-b border-term-amber px-2 py-0.5 bg-term-panel">
        <span className="text-term-amber tracking-wider uppercase text-term-sm">
          {title}
        </span>
        {right && <span className="text-term-textMuted text-term-xs">{right}</span>}
      </div>
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  );
}
