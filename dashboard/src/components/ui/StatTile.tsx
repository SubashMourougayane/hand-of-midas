import { ReactNode } from "react";
import { AnimatedNumber } from "./AnimatedNumber";

type Tone = "neutral" | "bull" | "bear" | "warn";

const VALUE_TONE: Record<Tone, string> = {
  neutral: "text-ink-primary",
  bull: "text-bull",
  bear: "text-bear",
  warn: "text-warn",
};

const BAR_TONE: Record<Tone, string> = {
  neutral: "bg-ink-secondary",
  bull: "bg-bull",
  bear: "bg-bear",
  warn: "bg-warn",
};

/**
 * Editorial KPI tile (operations-briefing style):
 *   LABEL (uppercase, letter-spaced)      [right chip]
 *   BIG MONO VALUE  unit
 *   sub caption
 *   ▁▁▁▁ mini progress bar (optional)
 * Designed to sit inside a bordered row of tiles separated by vertical rules.
 */
export function StatTile({
  label,
  value,
  unit,
  sub,
  right,
  tone = "neutral",
  progress,
  progressTone,
  animateOn,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  right?: ReactNode;
  tone?: Tone;
  /** 0–1 fill for the mini bar; omit to hide the bar */
  progress?: number | null;
  progressTone?: Tone;
  /** raw numeric — when it changes the value slides (up/down). omit = static */
  animateOn?: number | null;
}) {
  const pct =
    progress == null ? null : Math.max(0, Math.min(1, progress)) * 100;
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4 min-w-0 h-full">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-ds-xs uppercase tracking-[0.14em] text-ink-muted truncate">
          {label}
        </span>
        {right}
      </div>
      <div className="flex items-baseline gap-1 min-w-0">
        <span
          className={`font-mono text-[clamp(18px,2vw,26px)] leading-none font-bold tabular-nums truncate ${VALUE_TONE[tone]}`}
        >
          {animateOn !== undefined ? (
            <AnimatedNumber value={value} numeric={animateOn} />
          ) : (
            value
          )}
        </span>
        {unit && <span className="font-mono text-[10px] text-ink-muted shrink-0">{unit}</span>}
      </div>
      {sub && <div className="text-ds-xs text-ink-muted truncate">{sub}</div>}
      {/* Push the bar to the tile floor so every tile in a row lines up. */}
      {pct != null && (
        <div className="mt-auto pt-1.5 h-1.5 w-full">
          <div className="h-1 w-full rounded-full bg-white/[0.06] overflow-hidden">
            <div
              className={`h-full rounded-full ${BAR_TONE[progressTone ?? tone]} transition-[width] duration-500`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
