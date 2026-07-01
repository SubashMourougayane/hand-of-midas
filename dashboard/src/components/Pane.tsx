import { ReactNode } from "react";

export function Pane({
  title,
  subtitle,
  right,
  toolbar,
  children,
  className = "",
  padded = false,
  density = "normal",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
  density?: "compact" | "normal";
}) {
  return (
    <div
      className={`
        flex flex-col min-h-0
        bg-bg-surface border border-line-subtle rounded-ds
        shadow-ds-card
        ${className}
      `}
    >
      {(title || right || toolbar) && (
        <div className="flex flex-col border-b border-line-subtle">
          <div
            className={`flex items-center justify-between px-3 ${
              density === "compact" ? "py-1.5" : "py-2"
            }`}
          >
            <div className="flex items-baseline gap-2 min-w-0">
              {title && (
                <span className="text-ink-primary font-semibold text-ds-md tracking-tight truncate">
                  {title}
                </span>
              )}
              {subtitle && (
                <span className="text-ink-muted text-ds-xs truncate">
                  {subtitle}
                </span>
              )}
            </div>
            {right && (
              <div className="text-ink-secondary text-ds-xs flex items-center gap-2 shrink-0">
                {right}
              </div>
            )}
          </div>
          {toolbar && (
            <div className="px-3 py-1.5 border-t border-line-subtle bg-bg-base/40">
              {toolbar}
            </div>
          )}
        </div>
      )}
      <div className={`flex-1 overflow-auto ${padded ? "p-3" : ""}`}>{children}</div>
    </div>
  );
}
