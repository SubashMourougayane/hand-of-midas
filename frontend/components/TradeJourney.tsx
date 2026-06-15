"use client";
import { useState, useEffect } from "react";
import { ComposedChart, Line, Area, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { X } from "lucide-react";
import { formatINR } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { API_BASE } from "@/lib/client";

interface TradeJourneyProps {
  date: string;
  strategy: string;
  direction: string;
  entry: number;
  sl: number;
  tp: number;
  exit_price: number;
  pnl: number;
  bars_held: number;
  status: string;
  hold_human: string;
  onClose: () => void;
}

interface OHLCPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export default function TradeJourney({ date, strategy, direction, entry, sl, tp, exit_price, pnl, bars_held, status, hold_human, onClose }: TradeJourneyProps) {
  const { instrument } = useInstrument();
  const prefix = instrument === "oil" ? "oil" : "gold";
  const [points, setPoints] = useState<OHLCPoint[]>([]);
  const [entryIdx, setEntryIdx] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchJourney = async () => {
      try {
        const params = new URLSearchParams({
          date, strategy, direction: direction.toLowerCase(),
          entry: entry.toString(), sl: sl.toString(),
          tp: tp.toString(), bars_held: bars_held.toString(),
        });
        const res = await fetch(`${API_BASE}/api/${prefix}/journey?${params}`);
        const data = await res.json();
        setPoints(data.points || []);
        setEntryIdx(data.entry_bar_index || 0);
      } catch {}
      setLoading(false);
    };
    fetchJourney();
  }, [date, strategy, direction, entry, sl, tp, bars_held]);

  const stratColor = strategy.includes("alpha_sweep") ? "var(--color-info)" : strategy === "mean_rev" ? "var(--color-win)" : "var(--color-warn)";
  const stratLabel = strategy .includes("alpha_sweep") ? "Alpha-Sweep" : strategy === "mean_rev" ? "Mean-Rev" : "Cross-Market";
  const isLong = direction === "LONG";

  // Compute dynamic SL (break-even detection for Alpha-Sweep)
  const isAlphaSweep = strategy.includes("alpha_sweep");
  const beTarget = isAlphaSweep && tp > 0
    ? (isLong ? entry + (tp - entry) * 0.5 : entry - (entry - tp) * 0.5)
    : 0;
  const beOffset = instrument === "oil" ? 0.01 : 0.30;
  const beSl = isLong ? entry + beOffset : entry - beOffset;

  let beBarIdx = -1;
  if (isAlphaSweep && tp > 0 && points.length > 0) {
    for (let i = entryIdx + 1; i < points.length; i++) {
      if (isLong && points[i].high >= beTarget) { beBarIdx = i; break; }
      if (!isLong && points[i].low <= beTarget) { beBarIdx = i; break; }
    }
  }

  const chartData = points.map((p, i) => {
    let slLevel = sl;
    if (beBarIdx > 0 && i >= beBarIdx) {
      slLevel = beSl;
    }
    return { ...p, sl_level: slLevel };
  });

  // Y axis: include all OHLC values + levels
  const allValues = [
    ...points.map(p => p.high),
    ...points.map(p => p.low),
    entry, sl, ...(tp > 0 ? [tp] : []), ...(beBarIdx > 0 ? [beSl] : []),
  ];
  const yMin = allValues.length > 0 ? Math.min(...allValues) - 1 : 0;
  const yMax = allValues.length > 0 ? Math.max(...allValues) + 1 : 100;

  const entryTime = points[entryIdx]?.time || "";
  const exitIdx = Math.min(entryIdx + bars_held, points.length - 1);
  const exitTime = points[exitIdx]?.time || "";

  const formatTime = (t: string) => {
    if (!t) return "";
    const d = new Date(t);
    if (strategy .includes("alpha_sweep")) {
      return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
  };

  return (
    <div className="rounded-[5px] bg-[var(--color-surface-1)] border border-[var(--color-border)] p-4 mb-4 relative">
      <button
        onClick={onClose}
        className="absolute top-3 right-3 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
        aria-label="Close"
      >
        <X size={14} />
      </button>

      {/* Header */}
      <div className="flex items-center gap-3 mb-3 flex-wrap text-[12px]">
        <span className="num text-[var(--color-text-muted)]">{date}</span>
        <span className="font-semibold" style={{ color: stratColor }}>{stratLabel}</span>
        <span className={isLong ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}>{direction}</span>
        <span>Entry <span className="num text-[var(--color-info)]">${entry.toFixed(2)}</span></span>
        <span>SL <span className="num text-[var(--color-loss)]">${sl.toFixed(2)}</span></span>
        {tp > 0 && <span>TP <span className="num text-[var(--color-win)]">${tp.toFixed(2)}</span></span>}
        <span className={`num font-semibold ${pnl >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
          ${pnl >= 0 ? "+" : ""}{pnl.toFixed(0)} <span className="text-[10px] font-normal text-[var(--color-text-muted)]">({formatINR(pnl)})</span>
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[var(--color-brass-hi)]">{status}</span>
        <span className="text-[var(--color-text-muted)]">{hold_human}</span>
      </div>

      {/* Chart */}
      {loading ? (
        <div className="h-[220px] flex items-center justify-center text-xs text-[var(--color-text-muted)]">Loading...</div>
      ) : points.length === 0 ? (
        <div className="h-[220px] flex items-center justify-center text-xs text-[var(--color-text-muted)]">No data</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 10, right: 60, bottom: 20, left: 10 }}>
            <XAxis
              dataKey="time"
              tick={{ fontSize: 9, fill: "var(--color-text-muted)" }}
              tickFormatter={formatTime}
              interval={Math.max(Math.floor(points.length / 8), 1)}
            />
            <YAxis
              domain={[yMin, yMax]}
              tick={{ fontSize: 9, fill: "var(--color-text-muted)" }}
              tickFormatter={(v) => `$${v.toFixed(0)}`}
              width={50}
            />
            <Tooltip
              contentStyle={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border-hi)", borderRadius: 5, fontSize: 11, color: "var(--color-text)" }}
              formatter={(v, name) => [`$${Number(v).toFixed(2)}`, String(name)]}
              labelFormatter={(label) => formatTime(String(label))}
            />

            {/* High-Low range as shaded area */}
            <Area type="monotone" dataKey="high" stroke="none" fill="transparent" />
            <Area type="monotone" dataKey="low" stroke="none" fill="transparent" />

            {/* Entry horizontal */}
            <ReferenceLine y={entry} stroke="var(--color-info)" strokeDasharray="4 4" strokeWidth={1}
              label={{ value: `Entry $${entry.toFixed(0)}`, position: "right", fill: "var(--color-info)", fontSize: 9 }} />

            {/* SL line — steps down/up on break-even */}
            <Line type="stepAfter" dataKey="sl_level" stroke="var(--color-loss)" strokeWidth={1} strokeDasharray="4 4" dot={false} name="SL" isAnimationActive={false} />

            {/* TP horizontal */}
            {tp > 0 && <ReferenceLine y={tp} stroke="var(--color-win)" strokeDasharray="4 4" strokeWidth={1}
              label={{ value: `TP $${tp.toFixed(0)}`, position: "right", fill: "var(--color-win)", fontSize: 9 }} />}

            {entryTime && <ReferenceLine x={entryTime} stroke="var(--color-info)" strokeDasharray="3 3" strokeWidth={0.5} />}
            {exitTime && <ReferenceLine x={exitTime} stroke="var(--color-sys-gold-micro)" strokeDasharray="3 3" strokeWidth={1} />}

            {/* High/Low traces — brass faded */}
            <Line type="monotone" dataKey="high" stroke="var(--color-brass-dim)" strokeWidth={1} dot={false} name="High" strokeDasharray="2 1" />
            <Line type="monotone" dataKey="low" stroke="var(--color-brass-dim)" strokeWidth={1} dot={false} name="Low" strokeDasharray="2 1" />

            {/* Close price — main brass line */}
            <Line type="monotone" dataKey="close" stroke="var(--color-brass)" strokeWidth={1.5} dot={false} name="Close" />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-[11.5px] text-[var(--color-text-dim)] flex-wrap">
        <span className="flex items-center gap-1.5"><span className="w-3 border-t-2 border-[var(--color-brass)]" /> Close</span>
        <span className="flex items-center gap-1.5"><span className="w-3 border-t border-[var(--color-brass-dim)]" /> High/Low</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-0 border-t border-dashed border-[var(--color-info)]" /> Entry</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-0 border-t border-dashed border-[var(--color-loss)]" /> SL</span>
        {tp > 0 && <span className="flex items-center gap-1.5"><span className="w-3 h-0 border-t border-dashed border-[var(--color-win)]" /> TP</span>}
        <span className="flex items-center gap-1.5"><span className="w-3 h-0 border-t border-dashed border-[var(--color-sys-gold-micro)]" /> Exit</span>
      </div>
    </div>
  );
}
