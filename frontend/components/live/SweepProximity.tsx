"use client";
import { useInstrument } from "@/lib/instrument";
import { Card, Badge } from "@/components/ui";

interface ScanStatus {
  scan_active: boolean;
  tradeable: boolean;
  price: number;
  spread: number;
  asia_high: number;
  asia_low: number;
  asia_range: number;
  bearish_sweep_level: number;
  bullish_sweep_level: number;
  dist_to_bearish: number;
  dist_to_bullish: number;
  proximity_pct: number;
  sweep_direction: string;
  sweep_detected: boolean;
  sweep_status: string;
  sweep_info: string | null;
  daily_bias: string;
  trades_today: number;
  max_trades_per_day: number;
  utc_time: string;
  skip_reasons?: string[];
}

export function SweepProximity({ scan }: { scan: ScanStatus | null }) {
  const { instrument } = useInstrument();

  if (!scan || scan.dist_to_bearish === undefined) {
    return (
      <Card surface={1} padded className="mb-4">
        <div className="text-[12.5px] text-[var(--color-text-dim)]">Loading sweep proximity…</div>
      </Card>
    );
  }

  const isGaugeStale = scan.sweep_status === "EXPIRED" || scan.sweep_status === "TRADED";
  const isSweepActive = scan.sweep_detected && scan.sweep_status === "ACTIVE";
  const isOutsideRange = !scan.sweep_detected && scan.proximity_pct >= 100;

  let clampedPosition: number;
  if (isOutsideRange) clampedPosition = 50;
  else if (scan.sweep_direction === "bearish") clampedPosition = 50 + (scan.proximity_pct / 100) * 50;
  else clampedPosition = 50 - (scan.proximity_pct / 100) * 50;

  const totalRange = scan.bearish_sweep_level - scan.bullish_sweep_level;
  const asiaLowPct = totalRange > 0 ? ((scan.asia_low - scan.bullish_sweep_level) / totalRange) * 100 : 20;
  const asiaHighPct = totalRange > 0 ? ((scan.asia_high - scan.bullish_sweep_level) / totalRange) * 100 : 80;

  let dotColor: string;
  let gaugeLabel = "";
  if (isGaugeStale) {
    dotColor = "var(--color-text-muted)";
    gaugeLabel = scan.sweep_status === "TRADED" ? "Traded" : "Expired";
  } else if (isOutsideRange) {
    dotColor = "var(--color-text-muted)";
    gaugeLabel = scan.sweep_direction === "bullish" ? "Below range" : "Above range";
  } else if (isSweepActive) {
    dotColor = "var(--color-win)";
    gaugeLabel = "Sweep live";
  } else if (clampedPosition <= 20 || clampedPosition >= 80) {
    dotColor = clampedPosition >= 80 ? "var(--color-loss)" : "var(--color-win)";
  } else if (clampedPosition <= 35 || clampedPosition >= 65) {
    dotColor = clampedPosition >= 65 ? "var(--color-sys-gold-micro)" : "var(--color-win)";
  } else {
    dotColor = "var(--color-warn)";
  }

  const distBearish = Math.abs(scan.dist_to_bearish);
  const distBullish = Math.abs(scan.dist_to_bullish);
  const closestDist = Math.min(distBearish, distBullish);
  const shouldPulse = isSweepActive || (!isGaugeStale && !isOutsideRange && closestDist <= 5);

  const biasTone: "win" | "loss" | "neutral" = scan.daily_bias === "bullish" ? "win" : scan.daily_bias === "bearish" ? "loss" : "neutral";
  const needleAngle = -90 + (clampedPosition / 100) * 180;

  return (
    <Card surface={1} padded className="mb-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Sweep Proximity</h2>
        <div className="flex items-center gap-2 flex-wrap">
          {scan.sweep_detected ? (() => {
            const status = scan.sweep_status || "ACTIVE";
            const tone: "win" | "loss" | "info" | "neutral" =
              status === "ACTIVE" ? "win" :
              status === "EXPIRED" ? "neutral" :
              status === "TRADED" ? "info" : "loss";
            const anim = (status === "ACTIVE" || (status !== "EXPIRED" && status !== "TRADED")) ? "sweepFlash 0.8s ease-in-out infinite alternate" : "none";
            return (
              <span style={{ animation: anim }}>
                <Badge tone={tone} variant="soft">Sweep {status} ({scan.sweep_direction})</Badge>
              </span>
            );
          })() : null}
          {scan.skip_reasons && scan.skip_reasons.length > 0 ? (
            <Badge tone="warn" variant="soft">Skip: {scan.skip_reasons.join(", ")}</Badge>
          ) : null}
          <span className="num text-[11.5px] text-[var(--color-text-dim)]">UTC {scan.utc_time}</span>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row items-center sm:items-start gap-4 sm:gap-6">
        {/* Speedometer */}
        <div style={{ position: "relative", width: "220px", height: "130px", flexShrink: 0, opacity: isGaugeStale ? 0.35 : isOutsideRange ? 0.6 : 1, transition: "opacity 0.5s" }}>
          <svg viewBox="0 0 200 110" style={{ width: "100%", height: "100%" }}>
            <path d="M 15 100 A 85 85 0 0 1 185 100" fill="none" stroke="var(--color-surface-2)" strokeWidth="12" strokeLinecap="round" />
            <defs>
              <linearGradient id="sweepGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor={isGaugeStale ? "var(--color-border-hi)" : "var(--color-win)"} />
                <stop offset="40%" stopColor={isGaugeStale ? "var(--color-border-hi)" : "var(--color-win)"} />
                <stop offset="60%" stopColor={isGaugeStale ? "var(--color-border-hi)" : "var(--color-warn)"} />
                <stop offset="80%" stopColor={isGaugeStale ? "var(--color-border-hi)" : "var(--color-sys-gold-micro)"} />
                <stop offset="100%" stopColor={isGaugeStale ? "var(--color-border-hi)" : "var(--color-loss)"} />
              </linearGradient>
            </defs>
            <path d="M 15 100 A 85 85 0 0 1 185 100" fill="none" stroke="url(#sweepGrad)" strokeWidth="8" strokeLinecap="round" opacity="0.4" />
            <path d="M 15 100 A 85 85 0 0 1 185 100" fill="none" stroke="url(#sweepGrad)" strokeWidth="8" strokeLinecap="round"
              strokeDasharray={`${clampedPosition * 2.67} 267`} />
            <line x1={15 + (asiaLowPct / 100) * 170} y1="92" x2={15 + (asiaLowPct / 100) * 170} y2="100" stroke={isGaugeStale ? "var(--color-border-hi)" : "var(--color-sys-oil)"} strokeWidth="2" />
            <line x1={15 + (asiaHighPct / 100) * 170} y1="92" x2={15 + (asiaHighPct / 100) * 170} y2="100" stroke={isGaugeStale ? "var(--color-border-hi)" : "var(--color-sys-oil)"} strokeWidth="2" />
          </svg>

          {/* Needle */}
          <div style={{
            position: "absolute", bottom: "10px", left: "50%", transformOrigin: "bottom center",
            transform: `translateX(-50%) rotate(${needleAngle}deg)`,
            width: "2px", height: "70px",
            background: `linear-gradient(to top, ${dotColor}, transparent)`,
            transition: "transform 0.5s ease-out",
          }}>
            <div style={{
              position: "absolute", top: "0", left: "50%", transform: "translateX(-50%)",
              width: "8px", height: "8px", borderRadius: "50%", background: dotColor,
              boxShadow: shouldPulse ? `0 0 12px ${dotColor}` : `0 0 4px color-mix(in srgb, ${dotColor} 60%, transparent)`,
              animation: shouldPulse ? "sweepPulse 1s ease-in-out infinite" : "none",
            }} />
          </div>

          {/* Pivot */}
          <div style={{
            position: "absolute", bottom: "6px", left: "50%", transform: "translateX(-50%)",
            width: "10px", height: "10px", borderRadius: "50%", background: "var(--color-border)", border: "2px solid var(--color-border-hi)",
          }} />

          <div className="num text-[8px]" style={{ position: "absolute", bottom: "0", left: "4px", color: isGaugeStale ? "var(--color-text-muted)" : "var(--color-win)" }}>BULL</div>
          <div className="num text-[8px]" style={{ position: "absolute", bottom: "0", right: "4px", color: isGaugeStale ? "var(--color-text-muted)" : "var(--color-loss)" }}>BEAR</div>

          {/* Price */}
          <div style={{ position: "absolute", bottom: "22px", left: "50%", transform: "translateX(-50%)", textAlign: "center" }}>
            <div className="num" style={{ fontSize: "16px", fontWeight: 600, color: isGaugeStale ? "var(--color-text-muted)" : dotColor }}>${scan.price.toFixed(2)}</div>
            <div className="num text-[9px]" style={{ color: "var(--color-text-muted)" }}>
              {String(instrument) === "oil" || String(instrument) === "oil-micro" ? "BCO/USD" : "XAU/USD"}
            </div>
          </div>

          {gaugeLabel ? (
            <div style={{ position: "absolute", top: "8px", left: "50%", transform: "translateX(-50%)", textAlign: "center" }}>
              <span className="text-[9px] font-semibold uppercase tracking-[0.6px] px-1.5 py-0.5 rounded" style={{
                background: isSweepActive ? "color-mix(in srgb, var(--color-win) 15%, transparent)" : "var(--color-surface-2)",
                color: isSweepActive ? "var(--color-win)" : isOutsideRange ? "var(--color-text-muted)" : "var(--color-text-muted)",
                border: `1px solid ${isSweepActive ? "color-mix(in srgb, var(--color-win) 40%, transparent)" : "var(--color-border)"}`,
                animation: isSweepActive ? "sweepFlash 0.8s ease-in-out infinite alternate" : "none",
              }}>
                {gaugeLabel}
              </span>
            </div>
          ) : null}
        </div>

        {/* Stats */}
        <div className="w-full flex-1 grid grid-cols-2 gap-2">
          {(() => {
            const isOil = String(instrument) === "oil" || String(instrument) === "oil-micro";
            const dp = isOil ? 2 : 1;
            const lp = isOil ? 2 : 0;
            return (<>
              <Card surface={2} className="p-2.5">
                <div className="text-[9px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">Bearish sweep</div>
                <div className="num text-[14px] font-semibold" style={{ color: "var(--color-loss)" }}>
                  {scan.dist_to_bearish <= 0
                    ? <><span className="text-[10px]">Breached</span> ${Math.abs(scan.dist_to_bearish).toFixed(dp)} past</>
                    : `$${scan.dist_to_bearish.toFixed(dp)} away`}
                </div>
                <div className="num text-[9px] text-[var(--color-text-muted)]">Level: ${scan.bearish_sweep_level.toFixed(lp)}</div>
              </Card>
              <Card surface={2} className="p-2.5">
                <div className="text-[9px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">Bullish sweep</div>
                <div className="num text-[14px] font-semibold" style={{ color: "var(--color-win)" }}>
                  {scan.dist_to_bullish <= 0
                    ? <><span className="text-[10px]">Breached</span> ${Math.abs(scan.dist_to_bullish).toFixed(dp)} past</>
                    : `$${scan.dist_to_bullish.toFixed(dp)} away`}
                </div>
                <div className="num text-[9px] text-[var(--color-text-muted)]">Level: ${scan.bullish_sweep_level.toFixed(lp)}</div>
              </Card>
              <Card surface={2} className="p-2.5">
                <div className="text-[9px] uppercase tracking-[0.6px] text-[var(--color-text-muted)] mb-1">Daily bias</div>
                <Badge tone={biasTone} variant="soft">{scan.daily_bias}</Badge>
              </Card>
              <Card surface={2} className="p-2.5">
                <div className="text-[9px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">Trades today</div>
                <div className="num text-[14px] font-semibold text-[var(--color-text)]">{scan.trades_today} / {scan.max_trades_per_day}</div>
              </Card>
              <Card surface={2} className="p-2.5">
                <div className="text-[9px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">Asia range</div>
                <div className="num text-[14px] font-semibold" style={{ color: "var(--color-sys-oil)" }}>${scan.asia_range.toFixed(lp)}</div>
                <div className="num text-[9px] text-[var(--color-text-muted)]">${scan.asia_low.toFixed(lp)} – ${scan.asia_high.toFixed(lp)}</div>
              </Card>
              <Card surface={2} className="p-2.5">
                <div className="text-[9px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">Sweep status</div>
                <div className="text-[12px] font-semibold uppercase tracking-tight" style={{ color:
                  scan.sweep_status === "ACTIVE" ? "var(--color-win)" :
                  scan.sweep_status === "TRADED" ? "var(--color-sys-oil)" :
                  scan.sweep_status === "EXPIRED" ? "var(--color-text-muted)" : "var(--color-text-muted)"
                }}>
                  {scan.sweep_status || (scan.sweep_detected ? "DETECTED" : "WAITING")}
                </div>
              </Card>
            </>);
          })()}
        </div>
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes sweepPulse { 0%,100% { transform: translateX(-50%) scale(1); } 50% { transform: translateX(-50%) scale(1.4); } }
        @keyframes sweepFlash { 0% { opacity: 1; } 100% { opacity: 0.4; } }
      ` }} />
    </Card>
  );
}
