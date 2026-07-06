// Horizontal range bar with SL/TP markers and live-price tick (BlockTrade-style).
// skill: chart-type — match comparison/range data to bar viz with direct labeling.

export function RangeBar({
  side,
  entry,
  stop,
  tp,
  current,
  className = "",
  showLabels = true,
}: {
  side: 1 | -1;
  entry: number;
  stop: number;
  tp: number | null;
  current?: number | null;
  className?: string;
  showLabels?: boolean;
}) {
  if (tp == null) return null;
  // Axis is ALWAYS oriented SL(0%) → TP(100%), independent of price direction.
  // For a long tp>stop; for a short tp<stop — anchoring to stop/tp (not min/max)
  // keeps SL on the left + TP on the right for BOTH, so the live tick moves
  // RIGHT as the trade profits and LEFT as it loses, matching the labels.
  // (The old min/max axis flipped shorts: price rising = losing moved the tick
  // toward the "TP" label on the right — visually backwards.)
  const span = tp - stop || 1;
  const pct = (v: number) => ((v - stop) / span) * 100;
  const entryPct = pct(entry);
  const stopPct = pct(stop);   // = 0
  const tpPct = pct(tp);       // = 100
  const curPct = current != null ? Math.max(0, Math.min(100, pct(current))) : null;

  const stopColor = "bg-bear";
  const tpColor = "bg-bull";
  const entryColor = "bg-ink-secondary";
  const trackBull = side === 1;

  // Risk/reward zones — left of entry is loss (red bg), right is profit (green bg) for longs; reversed for shorts.
  // We orient by the actual stop/tp positions (regardless of side).
  const stopLeft = Math.min(entryPct, stopPct);
  const stopRight = Math.max(entryPct, stopPct);
  const tpLeft = Math.min(entryPct, tpPct);
  const tpRight = Math.max(entryPct, tpPct);

  return (
    <div className={`relative ${className}`}>
      {showLabels && (
        <div className="flex justify-between text-ds-xs text-ink-muted mb-1">
          <span className="font-mono">{stop.toFixed(2)}</span>
          <span className="font-mono">{entry.toFixed(2)}</span>
          <span className="font-mono">{tp.toFixed(2)}</span>
        </div>
      )}
      <div className="relative h-2 bg-bg-input rounded-full overflow-hidden border border-line-subtle">
        {/* loss zone (stop ↔ entry) */}
        <div
          className="absolute top-0 h-full bg-bear/15"
          style={{ left: `${stopLeft}%`, width: `${stopRight - stopLeft}%` }}
        />
        {/* profit zone (entry ↔ tp) */}
        <div
          className="absolute top-0 h-full bg-bull/15"
          style={{ left: `${tpLeft}%`, width: `${tpRight - tpLeft}%` }}
        />
        {/* current price line */}
        {curPct != null && (
          <div
            className="absolute top-[-2px] bottom-[-2px] w-[2px] bg-ink-primary z-20"
            style={{ left: `calc(${curPct}% - 1px)` }}
          />
        )}
        {/* entry marker */}
        <div
          className={`absolute top-[-2px] bottom-[-2px] w-[2px] ${entryColor} z-10`}
          style={{ left: `calc(${entryPct}% - 1px)` }}
        />
        {/* stop marker */}
        <div
          className={`absolute top-[-1px] bottom-[-1px] w-[2px] ${stopColor}`}
          style={{ left: `calc(${stopPct}% - 1px)` }}
        />
        {/* tp marker */}
        <div
          className={`absolute top-[-1px] bottom-[-1px] w-[2px] ${tpColor}`}
          style={{ left: `calc(${tpPct}% - 1px)` }}
        />
      </div>
      {showLabels && (
        <div className="flex justify-between text-ds-xs mt-1">
          <span className="text-bear">SL</span>
          <span className="text-ink-muted">{trackBull ? "LONG" : "SHORT"}</span>
          <span className="text-bull">TP</span>
        </div>
      )}
    </div>
  );
}
