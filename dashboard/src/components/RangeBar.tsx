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
  const clamp = (x: number) => Math.max(0, Math.min(100, x));
  const entryPct = pct(entry);
  const stopPct = pct(stop);   // = 0
  const tpPct = pct(tp);       // = 100
  const curPct = current != null ? clamp(pct(current)) : null;
  // +1R = the partial-TP / breakeven level: one risk-unit in profit from entry.
  const risk = Math.abs(entry - stop);
  const oneR = side === 1 ? entry + risk : entry - risk;
  const oneRPct = clamp(pct(oneR));
  const entryPctC = clamp(entryPct);
  // Break-even (stop trailed to entry): risk ≈ 0 collapses stop, entry AND +1R
  // onto the same point → labels overlap. Suppress the redundant entry/+1R labels
  // and markers; the SL label already shows that price (it IS the break-even).
  const beLike =
    risk === 0 || risk / Math.max(Math.abs(tp - entry), 1e-9) < 0.01;

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
        // Absolute-positioned so each price sits ABOVE its real marker (entry
        // near the SL for a tight-stop short, +1R between entry and TP), not
        // spread to fixed thirds.
        <div className="relative h-3.5 mb-1 text-ds-xs font-mono text-ink-muted">
          <span className="absolute left-0">{stop.toFixed(2)}{beLike ? " · BE" : ""}</span>
          {!beLike && (
            <span
              className="absolute text-ink-secondary whitespace-nowrap"
              style={{ left: `${entryPctC}%`, transform: "translateX(-50%)" }}
            >
              {entry.toFixed(2)}
            </span>
          )}
          {!beLike && (
            <span
              className="absolute text-warn whitespace-nowrap"
              style={{ left: `${oneRPct}%`, transform: "translateX(-50%)" }}
              title="+1R — partial-TP books here, stop moves to breakeven"
            >
              {oneR.toFixed(2)}
            </span>
          )}
          <span className="absolute right-0">{tp.toFixed(2)}</span>
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
        {/* +1R marker + zone (partial-TP / breakeven trigger) — hidden at BE
            where +1R collapses onto entry. */}
        {!beLike && (
          <>
            <div
              className="absolute top-[-2px] bottom-[-2px] w-[2px] bg-warn z-10"
              style={{ left: `calc(${oneRPct}% - 1px)` }}
            />
            <div
              className="absolute top-0 h-full bg-warn/20"
              style={{
                left: `${Math.min(entryPctC, oneRPct)}%`,
                width: `${Math.abs(oneRPct - entryPctC)}%`,
              }}
            />
          </>
        )}
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
