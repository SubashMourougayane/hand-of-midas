import { useMemo } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarWalkRow, Trade } from "../lib/api";
import { fmtPriceFor, fmtR, fmtTime } from "../lib/format";

// Pull a numeric fib field out of raw_features, tolerating string encodings.
function fibNum(rf: Record<string, unknown> | null | undefined, key: string): number | null {
  if (!rf) return null;
  const v = rf[key];
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

// Convert a price into an R-multiple relative to entry, signed by trade direction.
function priceToR(price: number, trade: Trade): number | null {
  const risk = Math.abs(trade.entry_price - trade.stop_price);
  if (risk === 0) return null;
  const dir = trade.side > 0 ? 1 : -1;
  return ((price - trade.entry_price) * dir) / risk;
}

type OffScale = { price: number; kind: "ENTRY" | "SL" | "TP"; edge: "top" | "bottom" };

function isOff(off: OffScale[], kind: OffScale["kind"]): boolean {
  return off.some((o) => o.kind === kind);
}

function nearestBar(ts: string | null | undefined, walk: BarWalkRow[]): number | null {
  if (!ts || walk.length === 0) return null;
  const t = new Date(ts).getTime();
  let best = 0;
  let bestDelta = Infinity;
  walk.forEach((b, i) => {
    const d = Math.abs(new Date(b.bar_ts).getTime() - t);
    if (d < bestDelta) {
      bestDelta = d;
      best = i;
    }
  });
  return best;
}

export function AnnotatedBarWalk({
  walk,
  trade,
  symbol,
}: {
  walk: BarWalkRow[];
  trade: Trade | null;
  symbol: string | null;
}) {
  const data = useMemo(
    () =>
      walk.map((b, i) => ({
        i,
        ts: b.bar_ts,
        label: b.bar_ts.slice(11, 16),
        close: b.close,
        high: b.high,
        low: b.low,
      })),
    [walk]
  );

  const fib382 = fibNum(trade?.raw_features, "fib_382");
  const fib786 = fibNum(trade?.raw_features, "fib_786");
  const fibLo = fib382 != null && fib786 != null ? Math.min(fib382, fib786) : null;
  const fibHi = fib382 != null && fib786 != null ? Math.max(fib382, fib786) : null;

  // ── Y-domain strategy ─────────────────────────────────────────────
  // Price-action range from the walk itself.
  const priceRange = useMemo(() => {
    if (walk.length === 0) return null;
    let lo = Infinity;
    let hi = -Infinity;
    for (const b of walk) {
      lo = Math.min(lo, b.low);
      hi = Math.max(hi, b.high);
    }
    return { lo, hi };
  }, [walk]);

  // Try to include entry/SL/TP. But if a bracket level is many multiples of the
  // bar range away, including it squashes the price line flat. In that case we
  // clamp the domain and pin the off-scale level as an edge marker instead.
  const { domain, offscale } = useMemo((): {
    domain: [number, number] | [string, string];
    offscale: OffScale[];
  } => {
    if (!priceRange || !trade) {
      return { domain: ["auto", "auto"], offscale: [] };
    }
    // ENTRY is the anchor — always include it so the price line reads relative
    // to where we got in, even on a young trade whose bars have run away from it.
    let lo = Math.min(priceRange.lo, trade.entry_price);
    let hi = Math.max(priceRange.hi, trade.entry_price);
    const barSpan = Math.max(hi - lo, 1e-6);
    const levels: { price: number; kind: OffScale["kind"] }[] = [
      { price: trade.stop_price, kind: "SL" },
    ];
    if (trade.take_profit_price != null)
      levels.push({ price: trade.take_profit_price, kind: "TP" });

    // Young trade (few bars) → show the FULL risk/reward geometry (entry+SL+TP),
    // never off-scale, so the setup reads at a glance. Only mature trades with a
    // real bar spread clamp far levels to edge pins.
    const youngTrade = walk.length < 10;
    const MAX_EXPAND = youngTrade ? Infinity : 4;
    const off: OffScale[] = [];
    for (const lvl of levels) {
      const distAbove = lvl.price - hi;
      const distBelow = lo - lvl.price;
      if (distAbove > MAX_EXPAND * barSpan) {
        off.push({ ...lvl, edge: "top" });
      } else if (distBelow > MAX_EXPAND * barSpan) {
        off.push({ ...lvl, edge: "bottom" });
      } else {
        lo = Math.min(lo, lvl.price);
        hi = Math.max(hi, lvl.price);
      }
    }
    const pad = Math.max((hi - lo) * 0.06, barSpan * 0.15);
    return { domain: [lo - pad, hi + pad], offscale: off };
  }, [priceRange, trade, walk.length]);

  const entryIdx = useMemo(
    () => nearestBar(trade?.entry_timestamp, walk),
    [trade?.entry_timestamp, walk]
  );
  const exitIdx = useMemo(
    () => nearestBar(trade?.exit_timestamp, walk),
    [trade?.exit_timestamp, walk]
  );

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-ink-muted text-ds-sm">
        No bar-walk data for this trade.
      </div>
    );
  }

  const priceLabel = (v: number | null | undefined, text: string, fill: string) => ({
    value: `${text} ${fmtPriceFor(symbol, v)}`,
    position: "right" as const,
    fill,
    fontSize: 9,
    fontFamily: "monospace",
  });

  const breakeven = trade?.partial_taken ? trade?.entry_price ?? null : null;

  return (
    <div className="h-full flex flex-col">
      {/* Off-scale pinned edge markers */}
      {offscale.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 pt-2 text-ds-xs font-mono">
          {offscale.map((o) => {
            const r = trade ? priceToR(o.price, trade) : null;
            const tone =
              o.kind === "TP"
                ? "text-bull"
                : o.kind === "SL"
                ? "text-bear"
                : "text-ink-secondary";
            return (
              <span key={o.kind} className={`inline-flex items-center gap-1 ${tone}`}>
                {o.edge === "top" ? "↑" : "↓"} {o.kind} {fmtPriceFor(symbol, o.price)}
                {r != null && <span className="text-ink-muted">({fmtR(r)}R)</span>}
                <span className="text-ink-dim">off-scale</span>
              </span>
            );
          })}
        </div>
      )}
      <div className="flex-1 min-h-0 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ left: 4, right: 68, top: 8, bottom: 4 }}>
            <defs>
              <linearGradient id="walkArea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22c55e" stopOpacity={0.22} />
                <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9, fill: "#8c95a4" }}
              minTickGap={32}
              axisLine={{ stroke: "#1f2733" }}
              tickLine={{ stroke: "#1f2733" }}
            />
            <YAxis
              tick={{ fontSize: 9, fill: "#8c95a4" }}
              domain={domain}
              width={52}
              tickFormatter={(v: number) => fmtPriceFor(symbol, v)}
              axisLine={{ stroke: "#1f2733" }}
              tickLine={{ stroke: "#1f2733" }}
            />
            <Tooltip
              contentStyle={{
                background: "#161c25",
                border: "1px solid #2c3645",
                borderRadius: 6,
                fontSize: 11,
                color: "#f1f3f6",
              }}
              labelStyle={{ color: "#8c95a4" }}
              labelFormatter={(_l, p) => {
                const ts = (p && p[0]?.payload?.ts) as string | undefined;
                return ts ? fmtTime(ts) : "";
              }}
              formatter={(value: number | string) => [
                fmtPriceFor(symbol, Number(value)),
                "Close",
              ]}
            />

            {/* Fib entry zone shading */}
            {fibLo != null && fibHi != null && (
              <ReferenceArea
                y1={fibLo}
                y2={fibHi}
                fill="#60a5fa"
                fillOpacity={0.08}
                stroke="#60a5fa"
                strokeOpacity={0.25}
                strokeDasharray="2 4"
                label={{
                  value: "fib 0.382–0.786",
                  position: "insideTopLeft",
                  fill: "#60a5fa",
                  fontSize: 9,
                }}
              />
            )}

            {/* Reference lines: entry / stop / take-profit (only when in-domain) */}
            {trade && !isOff(offscale, "ENTRY") && (
              <ReferenceLine
                y={trade.entry_price}
                stroke="#c8cdd6"
                strokeDasharray="4 3"
                label={priceLabel(trade.entry_price, "ENTRY", "#c8cdd6")}
              />
            )}
            {trade && !isOff(offscale, "SL") && (
              <ReferenceLine
                y={trade.stop_price}
                stroke="#f04452"
                strokeDasharray="4 3"
                label={priceLabel(trade.stop_price, "SL", "#f04452")}
              />
            )}
            {trade && trade.take_profit_price != null && !isOff(offscale, "TP") && (
              <ReferenceLine
                y={trade.take_profit_price}
                stroke="#4ade80"
                strokeDasharray="4 3"
                label={priceLabel(trade.take_profit_price, "TP", "#4ade80")}
              />
            )}
            {breakeven != null && (
              <ReferenceLine
                y={breakeven}
                stroke="#fbbf24"
                strokeDasharray="1 3"
                label={priceLabel(breakeven, "BE", "#fbbf24")}
              />
            )}

            <Area
              type="monotone"
              dataKey="close"
              stroke="#22c55e"
              strokeWidth={1.4}
              fill="url(#walkArea)"
            />
            <Line type="monotone" dataKey="close" stroke="#4ade80" dot={false} strokeWidth={1.4} />

            {/* Entry / exit markers */}
            {entryIdx != null && data[entryIdx] && (
              <ReferenceDot
                x={data[entryIdx].label}
                y={data[entryIdx].close}
                r={4}
                fill="#c8cdd6"
                stroke="#0a0b0d"
                strokeWidth={1.5}
              />
            )}
            {exitIdx != null && data[exitIdx] && (
              <ReferenceDot
                x={data[exitIdx].label}
                y={data[exitIdx].close}
                r={4}
                fill={trade?.exit_reason === "sl" ? "#f04452" : "#4ade80"}
                stroke="#0a0b0d"
                strokeWidth={1.5}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
