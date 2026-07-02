import { ReactNode } from "react";

/**
 * Editorial numbered section header — "01  Current Farm Status" with a
 * question subtitle underneath. Matches the operations-briefing reference.
 */
export function SectionHeader({
  index,
  title,
  question,
  right,
}: {
  index?: string;
  title: string;
  question?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-1">
      <div className="flex items-baseline gap-3 min-w-0">
        {index && (
          <span className="font-mono text-ds-sm text-ink-dim tabular-nums shrink-0">
            {index}
          </span>
        )}
        <div className="min-w-0">
          <h2 className="text-ds-lg font-semibold text-ink-primary tracking-tight">
            {title}
          </h2>
          {question && (
            <p className="mt-0.5 font-mono text-ds-xs text-ink-muted tracking-wide">
              {question}
            </p>
          )}
        </div>
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
