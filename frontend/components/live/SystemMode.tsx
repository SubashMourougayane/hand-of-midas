"use client";
import { useEffect, useState } from "react";
import { useInstrument } from "@/lib/instrument";
import { Card } from "@/components/ui";

export function SystemMode({ hasPositions }: { hasPositions: boolean }) {
  const { instrument } = useInstrument();
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();
  const utcTime = utcH + utcM / 60;
  const isWeekend = now.getUTCDay() === 0 || now.getUTCDay() === 6;

  // Determine mode
  let mode: string;
  let color: string;
  let icon: string;
  let countdown: string;

  if (isWeekend) {
    mode = "Market Closed";
    color = "var(--color-text-muted)";
    icon = "🌙";
    const sundayOpen = new Date(now);
    if (now.getUTCDay() === 6) {
      sundayOpen.setUTCDate(now.getUTCDate() + 1);
    } else {
      sundayOpen.setUTCDate(now.getUTCDate());
    }
    sundayOpen.setUTCHours(21, 0, 0, 0);
    const diff = sundayOpen.getTime() - now.getTime();
    const hrs = Math.floor(Math.max(diff, 0) / 3600000);
    const mins = Math.floor((Math.max(diff, 0) % 3600000) / 60000);
    countdown = diff > 0 ? `Opens in ${hrs}h ${mins}m` : "Opening soon…";
  } else if (hasPositions) {
    mode = "Position Open";
    color = "var(--color-win)";
    icon = "📈";
    countdown = "Monitoring every 1 min";
  } else if (instrument === "micro" || instrument === "oil-micro") {
    if (utcTime >= 21 && utcTime < 22) {
      mode = "Market Closed";
      color = "var(--color-text-muted)";
      icon = "🌙";
      const minsLeft = Math.floor((22 - utcTime) * 60);
      countdown = `Opens in ${minsLeft}m`;
    } else {
      mode = "Scanning";
      color = instrument === "oil-micro" ? "var(--color-sys-oil-micro)" : "var(--color-sys-gold-micro)";
      icon = "🔍";
      countdown = "Rolling windows active (22:00–21:00 UTC)";
    }
  } else if (utcTime >= 8 && utcTime <= 20) {
    mode = "Scanning";
    color = "var(--color-info)";
    icon = "🔍";
    const minsLeft = Math.floor((20 - utcTime) * 60);
    countdown = `Alpha-Sweep active · ${Math.floor(minsLeft / 60)}h ${minsLeft % 60}m remaining`;
  } else if (utcTime >= 21.95 && utcTime <= 22.1) {
    mode = "Daily Scan";
    color = "var(--color-warn)";
    icon = "⚡";
    countdown = "Running Cross-Market + Mean-Rev…";
  } else {
    mode = "Sleeping";
    color = "var(--color-text-muted)";
    icon = "💤";
    let nextEvent: string;
    let hoursUntil: number;
    if (utcTime < 8) {
      hoursUntil = 8 - utcTime;
      nextEvent = "Alpha-Sweep";
    } else if (utcTime < 22) {
      hoursUntil = 22 - utcTime;
      nextEvent = "Daily scan";
    } else {
      hoursUntil = 24 - utcTime + 8;
      nextEvent = "Alpha-Sweep";
    }
    const hrs = Math.floor(hoursUntil);
    const mins = Math.floor((hoursUntil - hrs) * 60);
    countdown = `Next: ${nextEvent} in ${hrs}h ${mins}m`;
  }

  const IST_OFFSET = 5.5;
  const istTime = (utcTime + IST_OFFSET) % 24;

  const tradingWindows = instrument === "micro" || instrument === "oil-micro"
    ? [
        { name: "Alpha-Sweep", start: 3.5, end: 24, color: instrument === "oil-micro" ? "var(--color-sys-oil-micro)" : "var(--color-sys-gold-micro)" },
        { name: "Alpha-Sweep", start: 0, end: 3, color: instrument === "oil-micro" ? "var(--color-sys-oil-micro)" : "var(--color-sys-gold-micro)" },
      ]
    : [
        { name: "Alpha-Sweep", start: 13.5, end: 24, color: "var(--color-info)" },
        { name: "Alpha-Sweep", start: 0, end: 1.5, color: "var(--color-info)" },
        { name: "Daily Scan", start: 3.5, end: 3.7, color: "var(--color-warn)" },
      ];

  return (
    <Card surface={1} padded className="mb-4 hom-fade-in-up">
      {/* Status row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg" aria-hidden>{icon}</span>
          <div className="flex flex-col">
            <span className="text-[12px] font-semibold tracking-tight" style={{ color }}>{mode}</span>
            <span className="text-[12.5px] text-[var(--color-text-dim)]">{countdown}</span>
          </div>
        </div>
        <span className="num text-[12.5px] text-[var(--color-text-dim)]">
          {now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true, timeZone: "Asia/Kolkata" })} IST
        </span>
      </div>

      {/* 24h Timeline — desktop only */}
      <div className="hidden md:block relative mt-4 px-1 sm:px-3 pb-2 overflow-x-auto">
        {/* Time label above needle */}
        <div className="relative h-5 mb-1">
          <div className="absolute z-20" style={{ left: `calc(${(istTime / 24) * 100}%)`, transform: "translateX(-50%)" }}>
            <span className="num text-[9px] font-semibold px-1.5 py-0.5 rounded" style={{ background: "var(--color-loss)", color: "#fff" }}>
              {now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" })}
            </span>
          </div>
        </div>

        {/* Sessions row */}
        <div className="relative h-11 mb-2 rounded" style={{ background: "var(--color-surface-1)" }}>
          {/* NY wrap (12 AM – 3:00 AM IST) */}
          {(() => {
            const nyActive = istTime >= 18.5 || istTime < 3;
            return (
              <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
                style={{
                  left: "0%", width: `${(3 / 24) * 100}%`,
                  background: nyActive ? "color-mix(in srgb, var(--color-sys-gold-micro) 15%, transparent)" : "color-mix(in srgb, var(--color-sys-gold-micro) 4%, transparent)",
                  border: nyActive ? "1.5px solid var(--color-sys-gold-micro)" : "1px solid color-mix(in srgb, var(--color-sys-gold-micro) 25%, transparent)",
                }}>
                <span className="text-[10px] font-semibold tracking-[0.6px]" style={{ color: nyActive ? "#fff" : "var(--color-sys-gold-micro)" }}>NY</span>
              </div>
            );
          })()}
          {/* CLOSED 3-3:30 AM IST */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center"
            style={{ left: `${(3 / 24) * 100}%`, width: `${(0.5 / 24) * 100}%` }}>
            <span className="text-[7px] font-bold" style={{ color: "var(--color-loss)" }}>✕</span>
          </div>
          {/* ASIA */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: `${(3.5 / 24) * 100}%`, width: `${(10 / 24) * 100}%`,
              background: (istTime >= 3.5 && istTime < 13.5) ? "color-mix(in srgb, var(--color-info) 15%, transparent)" : "color-mix(in srgb, var(--color-info) 4%, transparent)",
              border: (istTime >= 3.5 && istTime < 13.5) ? "1.5px solid var(--color-info)" : "1px solid color-mix(in srgb, var(--color-info) 25%, transparent)",
            }}>
            <span className="text-[10px] font-semibold tracking-[0.6px]" style={{ color: (istTime >= 3.5 && istTime < 13.5) ? "#fff" : "var(--color-info)" }}>Asia</span>
          </div>
          {/* LONDON */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: `${(13.5 / 24) * 100}%`, width: `${(5 / 24) * 100}%`,
              background: (istTime >= 13.5 && istTime < 18.5) ? "color-mix(in srgb, var(--color-sys-oil) 15%, transparent)" : "color-mix(in srgb, var(--color-sys-oil) 4%, transparent)",
              border: (istTime >= 13.5 && istTime < 18.5) ? "1.5px solid var(--color-sys-oil)" : "1px solid color-mix(in srgb, var(--color-sys-oil) 25%, transparent)",
            }}>
            <span className="text-[10px] font-semibold tracking-[0.6px]" style={{ color: (istTime >= 13.5 && istTime < 18.5) ? "#fff" : "var(--color-sys-oil)" }}>London</span>
          </div>
          {/* OVERLAP */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center"
            style={{
              left: `${(18.5 / 24) * 100}%`, width: `${(4 / 24) * 100}%`,
              background: (istTime >= 18.5 && istTime < 22.5)
                ? "linear-gradient(90deg, color-mix(in srgb, var(--color-sys-oil) 15%, transparent), color-mix(in srgb, var(--color-sys-gold-micro) 15%, transparent))"
                : "linear-gradient(90deg, color-mix(in srgb, var(--color-sys-oil) 5%, transparent), color-mix(in srgb, var(--color-sys-gold-micro) 5%, transparent))",
              borderTop: (istTime >= 18.5 && istTime < 22.5) ? "1.5px solid var(--color-brass)" : "1px solid color-mix(in srgb, var(--color-brass) 30%, transparent)",
              borderBottom: (istTime >= 18.5 && istTime < 22.5) ? "1.5px solid var(--color-brass)" : "1px solid color-mix(in srgb, var(--color-brass) 30%, transparent)",
            }}>
            <span className="text-[8px] font-semibold tracking-[0.6px]" style={{ color: "var(--color-brass-hi)" }}>Overlap</span>
          </div>
          {/* NEW YORK */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: `${(22.5 / 24) * 100}%`, width: `${(1.5 / 24) * 100}%`,
              background: (istTime >= 22.5) ? "color-mix(in srgb, var(--color-sys-gold-micro) 15%, transparent)" : "color-mix(in srgb, var(--color-sys-gold-micro) 4%, transparent)",
              border: (istTime >= 22.5) ? "1.5px solid var(--color-sys-gold-micro)" : "1px solid color-mix(in srgb, var(--color-sys-gold-micro) 25%, transparent)",
            }}>
            <span className="text-[10px] font-semibold tracking-[0.6px]" style={{ color: (istTime >= 22.5) ? "#fff" : "var(--color-sys-gold-micro)" }}>NY</span>
          </div>
        </div>

        {/* Trading windows */}
        <div className="relative h-10 mb-2 rounded" style={{ background: "var(--color-surface-1)" }}>
          {tradingWindows.map(w => {
            const isActive = w.name === "Alpha-Sweep"
              ? (istTime >= 13.5 || istTime <= 2.5)
              : (istTime >= w.start && istTime <= w.end);
            return (
              <div key={w.name + w.start} className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
                style={{
                  left: `${(w.start / 24) * 100}%`,
                  width: `${Math.max(((w.end - w.start) / 24) * 100, 2.5)}%`,
                  background: isActive ? `color-mix(in srgb, ${w.color} 30%, transparent)` : `color-mix(in srgb, ${w.color} 8%, transparent)`,
                  border: `1.5px solid ${isActive ? w.color : `color-mix(in srgb, ${w.color} 30%, transparent)`}`,
                  boxShadow: isActive ? `0 0 20px color-mix(in srgb, ${w.color} 25%, transparent)` : "none",
                }}>
                <span className="text-[10px] font-semibold tracking-tight" style={{ color: "#fff" }}>{w.name}</span>
              </div>
            );
          })}
          <div className="absolute top-1/2 left-0 right-0 pointer-events-none" style={{ opacity: 0.2 }}>
            <div className="w-full h-[1px]" style={{ background: "repeating-linear-gradient(90deg, var(--color-win) 0px, var(--color-win) 3px, transparent 3px, transparent 7px)" }} />
          </div>
        </div>

        {/* Hour scale */}
        <div className="relative h-5 mt-1">
          {Array.from({ length: 13 }).map((_, i) => {
            const h = i * 2;
            const label = h === 0 || h === 24 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`;
            return (
              <div key={h} className="absolute flex flex-col items-center" style={{ left: `${(h / 24) * 100}%`, transform: "translateX(-50%)" }}>
                <div className="w-[1px] h-1.5" style={{ background: "var(--color-border-hi)" }} />
                <span className="num text-[9px] mt-0.5 whitespace-nowrap" style={{ color: "var(--color-text-muted)" }}>{label}</span>
              </div>
            );
          })}
        </div>

        {/* Current time needle */}
        <div className="absolute z-10 pointer-events-none"
          style={{
            left: `calc(${(istTime / 24) * 100}% + 12px)`,
            top: "20px",
            height: "calc(100% - 44px)",
          }}>
          <div className="w-[2px] h-full mx-auto" style={{ background: "var(--color-loss)", boxShadow: "0 0 6px var(--color-loss)" }} />
        </div>
      </div>

      {/* Legend */}
      <div className="hidden md:flex flex-wrap items-center gap-3 sm:gap-5 mt-2 px-3 text-[11.5px] text-[var(--color-text-dim)]">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-2.5 rounded-sm" style={{ background: "color-mix(in srgb, var(--color-info) 15%, transparent)", border: "1px solid var(--color-info)" }} />
          Alpha-Sweep (9:30 AM – 1:30 AM)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-2.5 rounded-sm" style={{ background: "color-mix(in srgb, var(--color-warn) 15%, transparent)", border: "1px solid var(--color-warn)" }} />
          Daily Scan (3:30 AM)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="text-[8px] text-[var(--color-loss)]">✕</span>
          Closed (3:00–3:30 AM)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-[3px] h-3 rounded" style={{ background: "var(--color-loss)" }} />
          Now
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-5 h-[1px]" style={{ background: "repeating-linear-gradient(90deg, var(--color-win) 0px, var(--color-win) 3px, transparent 3px, transparent 6px)" }} />
          Monitor (24/7)
        </span>
      </div>
    </Card>
  );
}
