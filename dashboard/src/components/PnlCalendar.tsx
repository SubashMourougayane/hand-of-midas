import { useMemo, useState, useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Trade } from "../lib/api";
import { fmtMoney, fmtR, tradePnlReal } from "../lib/format";

// Calendar of daily cumulative $ + R, organized by month.
// Header shows year total in both $ and R.
// Each month tile shows month total $ + R.
// Each day cell shows day number; hover tooltip = date + $ + R.
export function PnlCalendar({
  trades,
  symbol,
}: {
  trades: Trade[];
  symbol?: string | null;
}) {
  const [viewYear, setViewYear] = useState<string>("");
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { dailyR, dailyUsd, years, allMonths } = useMemo(() => {
    const r: Record<string, number> = {};
    const u: Record<string, number> = {};
    trades.forEach((t) => {
      if (t.net_r == null || !t.entry_timestamp) return;
      const d = t.entry_timestamp.slice(0, 10);
      r[d] = (r[d] || 0) + (t.net_r ?? 0);
      const pnl = tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features, t.broker_net_usd) ?? 0;
      u[d] = (u[d] || 0) + pnl;
    });
    const months: Record<string, { date: string; r: number; usd: number }[]> = {};
    Object.entries(r)
      .sort()
      .forEach(([d, rv]) => {
        const key = d.slice(0, 7);
        if (!months[key]) months[key] = [];
        months[key].push({ date: d, r: rv, usd: u[d] ?? 0 });
      });
    const ys = Array.from(
      new Set(Object.keys(months).map((m) => m.slice(0, 4)))
    ).sort();
    return { dailyR: r, dailyUsd: u, years: ys, allMonths: months };
  }, [trades, symbol]);

  if (Object.keys(dailyR).length === 0) {
    return (
      <div className="px-3 py-8 text-center text-ink-muted text-ds-sm">
        No daily P&amp;L data.
      </div>
    );
  }

  const latestYear = years[years.length - 1];
  const activeYear = viewYear || latestYear;
  const yIdx = years.indexOf(activeYear);
  const canBack = yIdx > 0;
  const canFwd = yIdx < years.length - 1;

  const display = Array.from(
    { length: 12 },
    (_, i) => `${activeYear}-${String(i + 1).padStart(2, "0")}`
  ).filter((m) => allMonths[m]);

  const periodR = display.reduce(
    (s, m) => s + (allMonths[m]?.reduce((a, d) => a + d.r, 0) ?? 0),
    0
  );
  const periodUsd = display.reduce(
    (s, m) => s + (allMonths[m]?.reduce((a, d) => a + d.usd, 0) ?? 0),
    0
  );

  // Color intensity uses $ when symbol provided (more meaningful) else R.
  const useUsd = !!symbol;
  const dailyVal = useUsd ? dailyUsd : dailyR;
  const maxAbs = Math.max(...Object.values(dailyVal).map(Math.abs), 1) || 1;
  const colorFor = (v: number) => {
    const i = Math.min(Math.abs(v) / maxAbs, 1);
    if (v > 0) return `rgba(34, 197, 94, ${0.18 + i * 0.55})`;
    if (v < 0) return `rgba(240, 68, 82, ${0.18 + i * 0.55})`;
    return "transparent";
  };

  return (
    <div className="relative" ref={containerRef}>
      {tooltip && (
        <div
          className="absolute z-50 pointer-events-none px-2 py-1 font-mono text-[10px] font-semibold whitespace-nowrap rounded"
          style={{
            left: tooltip.x,
            top: tooltip.y,
            transform: "translate(-50%, -100%)",
            background: "rgba(20,22,25,0.9)",
            border: "1px solid rgba(255,255,255,0.14)",
            color: tooltip.text.includes("+") ? "#4ade80" : "#ff6b76",
          }}
        >
          {tooltip.text}
        </div>
      )}

      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
            Daily P&amp;L Calendar
          </span>
          <span
            className={`font-mono text-ds-md font-semibold ${
              periodUsd >= 0 ? "text-bull" : "text-bear"
            }`}
          >
            {fmtMoney(periodUsd, 0)}
          </span>
          <span
            className={`font-mono text-ds-xs ${
              periodR >= 0 ? "text-bull/70" : "text-bear/70"
            }`}
          >
            {fmtR(periodR)}R
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => canBack && setViewYear(years[yIdx - 1])}
            disabled={!canBack}
            className="w-6 h-6 flex items-center justify-center text-ink-muted hover:text-brass-hi disabled:opacity-20 transition-colors"
          >
            <ChevronLeft size={14} />
          </button>
          <span className="font-mono text-ds-sm font-semibold text-ink-primary">
            {activeYear}
          </span>
          <button
            onClick={() => canFwd && setViewYear(years[yIdx + 1])}
            disabled={!canFwd}
            className="w-6 h-6 flex items-center justify-center text-ink-muted hover:text-brass-hi disabled:opacity-20 transition-colors"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      <div className="px-3 pb-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
        {display.map((month) => {
          const days = allMonths[month] || [];
          const monthR = days.reduce((s, d) => s + d.r, 0);
          const monthUsd = days.reduce((s, d) => s + d.usd, 0);
          const sample = new Date(month + "-15");
          const y = sample.getFullYear();
          const mo = sample.getMonth();
          const firstDow = new Date(y, mo, 1).getDay();
          const daysIn = new Date(y, mo + 1, 0).getDate();
          const firstWeekday = firstDow === 0 ? 4 : firstDow === 6 ? 4 : firstDow - 1;

          const byDay: Record<number, { r: number; usd: number }> = {};
          days.forEach((d) => {
            const n = new Date(d.date).getDate();
            const cur = byDay[n] ?? { r: 0, usd: 0 };
            byDay[n] = { r: cur.r + d.r, usd: cur.usd + d.usd };
          });

          const cells: React.ReactNode[] = [];
          for (let i = 0; i < firstWeekday; i++) cells.push(<div key={`o-${i}`} />);
          for (let dn = 1; dn <= daysIn; dn++) {
            const dt = new Date(y, mo, dn);
            const dow = dt.getDay();
            if (dow === 0 || dow === 6) continue;
            const cell = byDay[dn];
            const has = cell !== undefined;
            const dayUsd = cell?.usd ?? 0;
            const dayR = cell?.r ?? 0;
            const dateStr = `${month}-${String(dn).padStart(2, "0")}`;
            const colorVal = useUsd ? dayUsd : dayR;
            cells.push(
              <div
                key={dn}
                className="w-full aspect-square flex items-center justify-center cursor-pointer rounded-[2px] hover:scale-110 transition-transform"
                style={{
                  background: has ? colorFor(colorVal) : "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.07)",
                }}
                onMouseEnter={(e) => {
                  if (!has) return;
                  const r = (e.target as HTMLElement).getBoundingClientRect();
                  const c = containerRef.current?.getBoundingClientRect();
                  setTooltip({
                    x: r.left - (c?.left || 0) + r.width / 2,
                    y: r.top - (c?.top || 0) - 4,
                    text: `${dateStr}  ${fmtMoney(dayUsd, 0)}  ·  ${fmtR(dayR)}R`,
                  });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                {has && (
                  <span className="font-mono text-[8px] font-semibold text-white/90">
                    {dn}
                  </span>
                )}
              </div>
            );
          }

          return (
            <div
              key={month}
              className="p-2 rounded-ds-sm"
              style={{
                background: "#0a0b0d",
                border: `1px solid ${
                  monthUsd >= 0
                    ? "rgba(52,211,153,0.20)"
                    : "rgba(248,113,113,0.20)"
                }`,
              }}
            >
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] font-semibold text-ink-primary">
                  {fmtMonth(month)}
                </span>
                <span
                  className={`font-mono text-[10px] font-semibold ${
                    monthUsd >= 0 ? "text-bull" : "text-bear"
                  }`}
                >
                  {fmtMoney(monthUsd, 0)}
                </span>
              </div>
              <div className="flex items-center justify-end mb-1">
                <span
                  className={`font-mono text-[9px] ${
                    monthR >= 0 ? "text-bull/60" : "text-bear/60"
                  }`}
                >
                  {fmtR(monthR)}R
                </span>
              </div>
              <div className="grid grid-cols-5 gap-[1px] mb-0.5">
                {["M", "T", "W", "T", "F"].map((d, i) => (
                  <span
                    key={d + i}
                    className="text-[7px] text-center text-ink-muted"
                  >
                    {d}
                  </span>
                ))}
              </div>
              <div className="grid grid-cols-5 gap-[1px]">{cells}</div>
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
