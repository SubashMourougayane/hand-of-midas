"use client";
import { useState, useRef } from "react";
import { Trade } from "@/lib/api";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { formatINR } from "@/lib/format";

export default function PnlCalendar({ trades }: { trades: Trade[] }) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [viewYear, setViewYear] = useState("");

  const dailyPnl: Record<string, number> = {};
  trades.forEach((t) => {
    dailyPnl[t.date] = (dailyPnl[t.date] || 0) + t.pnl_sized;
  });

  if (Object.keys(dailyPnl).length === 0) return null;

  const maxPnl = Math.max(...Object.values(dailyPnl).map(Math.abs), 1);
  const getColor = (pnl: number) => {
    const intensity = Math.min(Math.abs(pnl) / maxPnl, 1);
    if (pnl > 0) return `rgba(0, 232, 123, ${0.25 + intensity * 0.6})`;
    if (pnl < 0) return `rgba(255, 62, 62, ${0.25 + intensity * 0.6})`;
    return "transparent";
  };

  const allMonths: Record<string, { date: string; pnl: number }[]> = {};
  Object.entries(dailyPnl).sort().forEach(([d, pnl]) => {
    const dt = new Date(d);
    const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`;
    if (!allMonths[key]) allMonths[key] = [];
    allMonths[key].push({ date: d, pnl });
  });

  const monthKeys = Object.keys(allMonths).sort();
  const years = [...new Set(monthKeys.map(k => k.split("-")[0]))].sort();
  const latestYear = years[years.length - 1];
  const activeYear = viewYear || latestYear;

  // Show Jan-Dec for the selected year
  const display = Array.from({ length: 12 }, (_, i) => `${activeYear}-${String(i + 1).padStart(2, "0")}`)
    .filter(m => allMonths[m]);

  const periodPnl = display.reduce((sum, m) => sum + (allMonths[m]?.reduce((s, d) => s + d.pnl, 0) || 0), 0);
  const yearIdx = years.indexOf(activeYear);
  const canGoBack = yearIdx > 0;
  const canGoForward = yearIdx < years.length - 1;

  return (
    <div className="t-panel p-4 relative" ref={containerRef}>
      {/* Tooltip */}
      {tooltip && (
        <div className="absolute z-50 pointer-events-none px-2 py-1 text-[10px] font-semibold whitespace-nowrap"
          style={{
            left: tooltip.x, top: tooltip.y,
            transform: "translate(-50%, -100%)",
            background: "#181c24", border: "1px solid #252a33",
            color: tooltip.text.includes("+") ? "#00e87b" : "#ff3e3e",
          }}>
          {tooltip.text}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-wider font-bold text-[var(--text-dim)]">DAILY P&L CALENDAR</span>
          <span className="text-[10px] font-bold" style={{ color: periodPnl >= 0 ? "#00e87b" : "#ff3e3e" }}>
            {periodPnl >= 0 ? "+" : ""}${periodPnl.toFixed(0)} ({formatINR(periodPnl)})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => canGoBack && setViewYear(years[yearIdx - 1])} disabled={!canGoBack}
            className="w-5 h-5 flex items-center justify-center text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-20">
            <ChevronLeft size={12} />
          </button>
          <span className="text-xs font-bold text-[var(--text)]">{activeYear}</span>
          <button onClick={() => canGoForward && setViewYear(years[yearIdx + 1])} disabled={!canGoForward}
            className="w-5 h-5 flex items-center justify-center text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-20">
            <ChevronRight size={12} />
          </button>
        </div>
      </div>

      {/* Compact multi-month grid */}
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        {display.map((month) => {
          const days = allMonths[month] || [];
          const monthPnl = days.reduce((s, d) => s + d.pnl, 0);

          const sampleDate = new Date(month + "-15");
          const year = sampleDate.getFullYear();
          const mo = sampleDate.getMonth();
          const firstDay = new Date(year, mo, 1).getDay();
          const daysInMonth = new Date(year, mo + 1, 0).getDate();
          const firstWeekday = firstDay === 0 ? 4 : (firstDay === 6 ? 4 : firstDay - 1);

          const pnlByDay: Record<number, number> = {};
          days.forEach(d => {
            const dayNum = new Date(d.date).getDate();
            pnlByDay[dayNum] = (pnlByDay[dayNum] || 0) + d.pnl;
          });

          const cells: React.ReactNode[] = [];
          for (let i = 0; i < firstWeekday; i++) {
            cells.push(<div key={`off-${i}`} />);
          }
          for (let dayNum = 1; dayNum <= daysInMonth; dayNum++) {
            const dt = new Date(year, mo, dayNum);
            const dow = dt.getDay();
            if (dow === 0 || dow === 6) continue;
            const hasTrade = pnlByDay[dayNum] !== undefined;
            const pnl = pnlByDay[dayNum] || 0;
            const dateStr = `${month}-${String(dayNum).padStart(2, "0")}`;
            cells.push(
              <div key={dayNum}
                className="w-full aspect-square flex items-center justify-center cursor-pointer"
                style={{ background: hasTrade ? getColor(pnl) : "#0d1117", border: "1px solid #1a1f2b" }}
                onMouseEnter={(e) => {
                  if (!hasTrade) return;
                  const rect = (e.target as HTMLElement).getBoundingClientRect();
                  const cRect = containerRef.current?.getBoundingClientRect();
                  setTooltip({
                    x: rect.left - (cRect?.left || 0) + rect.width / 2,
                    y: rect.top - (cRect?.top || 0) - 4,
                    text: `${dateStr} | ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(0)} (${formatINR(pnl)})`,
                  });
                }}
                onMouseLeave={() => setTooltip(null)}>
                {hasTrade && <span className="text-[6px] font-bold text-white">{dayNum}</span>}
              </div>
            );
          }

          return (
            <div key={month} className="p-2" style={{ background: "#0a0d12", border: `1px solid ${monthPnl >= 0 ? "#00e87b22" : "#ff3e3e22"}` }}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[8px] font-bold text-[var(--text)]">{fmtMonth(month)}</span>
                <span className="text-[9px] font-bold" style={{ color: monthPnl >= 0 ? "#00e87b" : "#ff3e3e" }}>
                  {monthPnl >= 0 ? "+" : ""}${monthPnl.toFixed(0)}
                </span>
              </div>
              <div className="grid grid-cols-5 gap-[1px] mb-0.5">
                {["M", "T", "W", "T", "F"].map((d, i) => (
                  <span key={d + i} className="text-[5px] text-center text-[var(--text-dim)]">{d}</span>
                ))}
              </div>
              <div className="grid grid-cols-5 gap-[1px]">
                {cells}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function fmtMonth(key: string) {
  const d = new Date(key + "-15");
  return d.toLocaleDateString("en", { month: "short", year: "2-digit" });
}
