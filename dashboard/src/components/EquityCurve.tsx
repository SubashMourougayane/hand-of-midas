import { useMemo } from "react";
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { Trade } from "../lib/api";
import { fmtMoney, fmtR, tradePnlReal } from "../lib/format";

// Cumulative P&L curve. $-primary when symbol provided, R-secondary in tooltip.
export function EquityCurve({
  trades,
  symbol,
}: {
  trades: Trade[];
  symbol?: string | null;
}) {
  const data = useMemo(() => {
    const closed = trades
      .filter((t) => t.net_r != null && t.entry_timestamp)
      .sort(
        (a, b) =>
          new Date(a.entry_timestamp).getTime() -
          new Date(b.entry_timestamp).getTime()
      );
    let cumR = 0;
    let cumD = 0;
    return closed.map((t) => {
      cumR += t.net_r ?? 0;
      cumD += tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features) ?? 0;
      return {
        ts: t.entry_timestamp.slice(0, 10),
        cum: cumD,
        cumR,
      };
    });
  }, [trades, symbol]);

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-ink-muted text-ds-sm">
        No closed trades yet.
      </div>
    );
  }

  const final = data[data.length - 1]?.cum ?? 0;
  const finalR = data[data.length - 1]?.cumR ?? 0;
  const positive = final >= 0;

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 pt-2 pb-1 flex items-baseline gap-3">
        <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
          Cumulative P&amp;L
        </span>
        <span
          className={`font-mono text-ds-md font-semibold ${
            positive ? "text-bull" : "text-bear"
          }`}
        >
          {fmtMoney(final, 0)}
        </span>
        <span className="font-mono text-ds-xs text-ink-muted">
          {fmtR(finalR)}R
        </span>
        <span className="text-ds-xs text-ink-muted">
          across {data.length.toLocaleString()} trades
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ left: 4, right: 12, top: 4, bottom: 4 }}>
            <defs>
              <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="ts"
              tick={{ fontSize: 10, fill: "#8c95a4" }}
              minTickGap={40}
              axisLine={{ stroke: "#1f2733" }}
              tickLine={{ stroke: "#1f2733" }}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#8c95a4" }}
              axisLine={{ stroke: "#1f2733" }}
              tickLine={{ stroke: "#1f2733" }}
              width={40}
            />
            <Tooltip
              contentStyle={{
                background: "#161c25",
                border: "1px solid #2c3645",
                borderRadius: 6,
                fontSize: 12,
                color: "#f1f3f6",
              }}
              labelStyle={{ color: "#8c95a4" }}
              formatter={(value: any, name: string) => {
                if (name === "cum") return [fmtMoney(Number(value), 0), "P&L"];
                if (name === "cumR") return [`${Number(value).toFixed(2)}R`, "R"];
                return [value, name];
              }}
            />
            <ReferenceLine y={0} stroke="#3a4554" strokeDasharray="2 4" />
            <Area
              type="monotone"
              dataKey="cum"
              stroke="#10b981"
              strokeWidth={1.6}
              fill="url(#equityFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
