"use client";
import { Card, Badge } from "@/components/ui";

export function MicroWindows({ scan }: { scan: Record<string, unknown> }) {
  const windows = (scan as { active_windows?: Array<{
    start: number; end: number; scan_until: number; status: string;
    range_high: number; range_low: number; range: number;
    sweep_detected: boolean; sweep_info: { direction: string; wick: number } | null;
  }> }).active_windows || [];
  const price = (scan as { price?: number }).price || 0;
  const bias = (scan as { daily_bias?: string }).daily_bias || "neutral";
  const tradesToday = (scan as { trades_today?: number }).trades_today || 0;
  const maxTrades = (scan as { max_trades_per_day?: number }).max_trades_per_day || 3;
  const skipReasons = (scan as { skip_reasons?: string[] }).skip_reasons || [];

  const biasTone: "win" | "loss" | "neutral" = bias === "bullish" ? "win" : bias === "bearish" ? "loss" : "neutral";

  const toIST12 = (utcH: number) => {
    const ist = (utcH + 5.5) % 24;
    const h = Math.floor(ist);
    const m = (ist % 1) * 60;
    const hr12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
    const ampm = h < 12 ? "AM" : "PM";
    return m > 0 ? `${hr12}:${String(Math.round(m)).padStart(2, "0")} ${ampm}` : `${hr12} ${ampm}`;
  };

  // Sort chronologically by IST market day (starts 22:00 UTC = 3:30 AM IST)
  const sorted = [...windows].sort((a, b) => {
    const aKey = (a.start - 22 + 24) % 24;
    const bKey = (b.start - 22 + 24) % 24;
    return aKey - bKey;
  });

  return (
    <Card surface={1} padded className="mb-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h2 className="text-[10px] font-semibold uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Micro Scanner</h2>
          <span className="num text-[18px] font-semibold text-[var(--color-text)]">${price.toFixed(2)}</span>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={biasTone} variant="soft">{bias}</Badge>
          <span className="num text-[12.5px] text-[var(--color-text-dim)]">{tradesToday}/{maxTrades}</span>
          {skipReasons.length > 0 && (
            <Badge tone="warn" variant="soft">{skipReasons.join(", ")}</Badge>
          )}
        </div>
      </div>

      {/* Timeline rows */}
      <div className="flex flex-col gap-1.5">
        {sorted.map((w, i) => {
          const isActive = w.status === "scanning";
          const hasSweep = w.sweep_detected && w.sweep_info;
          const isBuilding = w.status === "building";
          const isExpired = w.status === "expired" || w.status === "range_too_small";

          let progress = 0;
          if (isBuilding) progress = 30;
          else if (isActive && !hasSweep) progress = 60;
          else if (isActive && hasSweep) progress = 80;
          else if (isExpired) progress = 100;

          let barColor = "var(--color-border-hi)";
          let textColor = "var(--color-text-muted)";
          let borderLeft = "3px solid var(--color-border-hi)";
          if (isActive && hasSweep) {
            barColor = "var(--color-sys-gold-micro)";
            textColor = "var(--color-sys-gold-micro)";
            borderLeft = "3px solid var(--color-sys-gold-micro)";
          } else if (isActive) {
            barColor = "var(--color-win)";
            textColor = "var(--color-win)";
            borderLeft = "3px solid var(--color-win)";
          } else if (hasSweep) {
            barColor = "color-mix(in srgb, var(--color-sys-gold-micro) 60%, transparent)";
            textColor = "var(--color-sys-gold-micro)";
            borderLeft = "3px solid color-mix(in srgb, var(--color-sys-gold-micro) 40%, transparent)";
          } else if (isBuilding) {
            barColor = "var(--color-info)";
            textColor = "var(--color-info)";
            borderLeft = "3px solid color-mix(in srgb, var(--color-info) 40%, transparent)";
          }

          let statusText = "";
          if (isActive && hasSweep) statusText = `⚡ ${w.sweep_info!.direction} sweep detected → searching for engulfing candle…`;
          else if (isActive) statusText = "Scanning for price to sweep beyond range and snap back";
          else if (hasSweep && isExpired) statusText = `⚡ ${w.sweep_info!.direction} sweep found but no engulfing formed in time`;
          else if (isBuilding) statusText = "Building consolidation range (price ranging)";
          else if (w.status === "range_too_small") statusText = "Range too small to trade (<$5)";
          else statusText = "Window closed — no opportunity";

          return (
            <div key={i} className="flex items-stretch gap-3 py-2 px-3 rounded-[4px]" style={{
              background: isActive ? `color-mix(in srgb, ${barColor} 10%, transparent)` : "transparent",
              borderLeft,
              opacity: isExpired && !hasSweep ? 0.5 : 1,
            }}>
              <div className="w-[140px] flex-shrink-0">
                <div className="num text-[12px] font-semibold text-[var(--color-text)]">{toIST12(w.start)} – {toIST12(w.end)}</div>
                {isActive && (
                  <div className="num text-[10px]" style={{ color: textColor }}>until {toIST12(w.scan_until)}</div>
                )}
              </div>

              <div className="w-[80px] flex-shrink-0 flex items-center">
                <div className="w-full h-[6px] rounded-full overflow-hidden" style={{ background: "var(--color-surface-2)" }}>
                  <div className="h-full rounded-full transition-all" style={{ width: `${progress}%`, background: barColor }} />
                </div>
              </div>

              <div className="flex-1 min-w-0">
                <div className="text-[11px]" style={{ color: textColor }}>{statusText}</div>
                {w.range > 0 && (
                  <div className="num text-[11.5px] text-[var(--color-text-dim)]">
                    Range ${w.range.toFixed(0)}{hasSweep && w.sweep_info ? ` · Wick $${w.sweep_info.wick.toFixed(0)}` : ""}
                  </div>
                )}
              </div>

              {isActive && (
                <div className="flex-shrink-0 flex items-center">
                  <div className="w-2.5 h-2.5 rounded-full animate-ping" style={{ background: barColor, opacity: 0.75 }} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {windows.length === 0 && (
        <div className="text-center text-[12.5px] text-[var(--color-text-dim)] py-4">
          No active windows (outside scan hours 04:00–20:00 UTC)
        </div>
      )}
    </Card>
  );
}
