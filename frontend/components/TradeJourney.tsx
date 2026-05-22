"use client";
import { useState, useEffect } from "react";
import { ComposedChart, Line, Area, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { X } from "lucide-react";
import { formatINR } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";

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
  const { apiBase, instrument } = useInstrument();
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
        const res = await fetch(`${apiBase}/api/${prefix}/journey?${params}`);
        const data = await res.json();
        setPoints(data.points || []);
        setEntryIdx(data.entry_bar_index || 0);
      } catch {}
      setLoading(false);
    };
    fetchJourney();
  }, [date, strategy, direction, entry, sl, tp, bars_held]);

  const stratColor = strategy .includes("alpha_sweep") ? "#4fc3f7" : strategy === "mean_rev" ? "#00e87b" : "#ffd54f";
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
    <div className="t-panel p-4 mb-4 relative">
      <button onClick={onClose} className="absolute top-3 right-3 text-[var(--text-dim)] hover:text-[var(--text)]">
        <X size={14} />
      </button>

      {/* Header */}
      <div className="flex items-center gap-3 mb-3 flex-wrap text-xs">
        <span className="text-[var(--text-dim)]">{date}</span>
        <span className="font-semibold" style={{ color: stratColor }}>{stratLabel}</span>
        <span className={isLong ? "text-[var(--green)]" : "text-[var(--red)]"}>{direction}</span>
        <span>Entry <span className="text-[#4da6ff]">${entry.toFixed(2)}</span></span>
        <span>SL <span className="text-[#ff3e3e]">${sl.toFixed(2)}</span></span>
        {tp > 0 && <span>TP <span className="text-[#00e87b]">${tp.toFixed(2)}</span></span>}
        <span className={`font-bold ${pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
          ${pnl >= 0 ? "+" : ""}{pnl.toFixed(0)} <span className="text-[9px] font-normal text-[var(--text-dim)]">({formatINR(pnl)})</span>
        </span>
        <span className="text-[var(--yellow)]">{status.toUpperCase()}</span>
        <span className="text-[var(--text-dim)]">{hold_human}</span>
      </div>

      {/* Chart */}
      {loading ? (
        <div className="h-[220px] flex items-center justify-center text-xs text-[var(--text-dim)]">Loading...</div>
      ) : points.length === 0 ? (
        <div className="h-[220px] flex items-center justify-center text-xs text-[var(--text-dim)]">No data</div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 10, right: 60, bottom: 20, left: 10 }}>
            <XAxis
              dataKey="time"
              tick={{ fontSize: 9, fill: "#9ca3b4" }}
              tickFormatter={formatTime}
              interval={Math.max(Math.floor(points.length / 8), 1)}
            />
            <YAxis
              domain={[yMin, yMax]}
              tick={{ fontSize: 9, fill: "#9ca3b4" }}
              tickFormatter={(v) => `$${v.toFixed(0)}`}
              width={50}
            />
            <Tooltip
              contentStyle={{ background: "#181c24", border: "1px solid #252a33", fontSize: 10 }}
              formatter={(v, name) => [`$${Number(v).toFixed(2)}`, String(name)]}
              labelFormatter={(label) => formatTime(String(label))}
            />

            {/* High-Low range as shaded area */}
            <Area type="monotone" dataKey="high" stroke="none" fill="transparent" />
            <Area type="monotone" dataKey="low" stroke="none" fill="transparent" />

            {/* Entry horizontal (blue) */}
            <ReferenceLine y={entry} stroke="#4da6ff" strokeDasharray="4 4" strokeWidth={1}
              label={{ value: `Entry $${entry.toFixed(0)}`, position: "right", fill: "#4da6ff", fontSize: 9 }} />

            {/* SL line (red) — steps down/up on break-even */}
            <Line type="stepAfter" dataKey="sl_level" stroke="#ff3e3e" strokeWidth={1} strokeDasharray="4 4" dot={false} name="SL" isAnimationActive={false} />

            {/* TP horizontal (green) */}
            {tp > 0 && <ReferenceLine y={tp} stroke="#00e87b" strokeDasharray="4 4" strokeWidth={1}
              label={{ value: `TP $${tp.toFixed(0)}`, position: "right", fill: "#00e87b", fontSize: 9 }} />}

            {/* Entry vertical (blue) */}
            {entryTime && <ReferenceLine x={entryTime} stroke="#4da6ff" strokeDasharray="3 3" strokeWidth={0.5} />}

            {/* Exit vertical (orange) */}
            {exitTime && <ReferenceLine x={exitTime} stroke="#ff8c00" strokeDasharray="3 3" strokeWidth={1} />}

            {/* High line (shows where SL/TP could trigger) */}
            <Line type="monotone" dataKey="high" stroke="#e8c30080" strokeWidth={1} dot={false} name="High" strokeDasharray="2 1" />

            {/* Low line (shows where SL/TP could trigger) */}
            <Line type="monotone" dataKey="low" stroke="#e8c30080" strokeWidth={1} dot={false} name="Low" strokeDasharray="2 1" />

            {/* Close price (main yellow line) */}
            <Line type="monotone" dataKey="close" stroke="#e8c300" strokeWidth={1.5} dot={false} name="Close" />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-[8px] text-[var(--text-dim)]">
        <span className="flex items-center gap-1"><span className="w-3 border-t-2 border-[#e8c300]" /> Close</span>
        <span className="flex items-center gap-1"><span className="w-3 border-t border-[#e8c30050]" /> High/Low</span>
        <span className="flex items-center gap-1"><span className="w-3 h-0 border-t border-dashed border-[#4da6ff]" /> Entry</span>
        <span className="flex items-center gap-1"><span className="w-3 h-0 border-t border-dashed border-[#ff3e3e]" /> SL</span>
        {tp > 0 && <span className="flex items-center gap-1"><span className="w-3 h-0 border-t border-dashed border-[#00e87b]" /> TP</span>}
        <span className="flex items-center gap-1"><span className="w-3 h-0 border-t border-dashed border-[#ff8c00]" /> Exit</span>
      </div>
    </div>
  );
}
