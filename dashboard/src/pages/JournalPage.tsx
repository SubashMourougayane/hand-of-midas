import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, BarWalkRow, JournalEvt, Trade } from "../lib/api";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import {
  colorForGateStatus,
  colorForR,
  fmtPrice,
  fmtR,
  fmtTs,
  shortGateLabel,
} from "../lib/format";

export function JournalPage({ runId }: { runId: string | null }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [journal, setJournal] = useState<JournalEvt[]>([]);
  const [walk, setWalk] = useState<BarWalkRow[]>([]);
  const [search] = useSearchParams();

  useEffect(() => {
    if (!runId) return;
    api.runTrades(runId, undefined, 1, 200).then(({ items }) => {
      setTrades(items);
      const fromQuery = search.get("trade");
      const pick = fromQuery && items.find((t) => t.trade_id === fromQuery);
      if (pick) setTradeId(pick.trade_id);
      else if (!tradeId && items.length > 0) setTradeId(items[0].trade_id);
    });
  }, [runId]);

  useEffect(() => {
    if (!tradeId) {
      setJournal([]);
      setWalk([]);
      return;
    }
    Promise.all([api.tradeJournal(tradeId), api.tradeBarWalk(tradeId)]).then(
      ([j, w]) => {
        setJournal(j);
        setWalk(w);
      }
    );
  }, [tradeId]);

  const trade = useMemo(
    () => trades.find((t) => t.trade_id === tradeId) ?? null,
    [trades, tradeId]
  );

  const chartData = useMemo(
    () =>
      walk.map((b) => ({
        ts: b.bar_ts.slice(11, 19),
        close: b.close,
        mfe_r: b.mfe_r,
        mae_r: b.mae_r,
        unreal: b.unrealised_r,
      })),
    [walk]
  );

  return (
    <div className="h-full grid grid-cols-12 gap-3 p-3 min-h-0">
      {/* ── Trade list ── */}
      <Pane title="Trades" subtitle={`${trades.length}`} className="col-span-2">
        <div className="divide-y divide-line-subtle">
          {trades.length === 0 && (
            <div className="px-3 py-8 text-center text-ink-muted text-ds-sm">
              No trades in this run
            </div>
          )}
          {trades.map((t) => {
            const active = t.trade_id === tradeId;
            const closed = t.exit_timestamp != null;
            return (
              <button
                key={t.trade_id}
                onClick={() => setTradeId(t.trade_id)}
                className={`
                  w-full text-left px-3 py-2 transition-colors duration-ds
                  ${active ? "bg-bg-elevated" : "hover:bg-bg-elevated/60"}
                `}
              >
                <div className="flex items-center gap-2 mb-0.5">
                  <Pill tone={t.side > 0 ? "bull" : "bear"}>
                    {t.direction.toUpperCase()}
                  </Pill>
                  {!closed && <Pill tone="info">OPEN</Pill>}
                  {closed && (
                    <span className={`font-mono text-ds-sm font-medium ${colorForR(t.net_r)}`}>
                      {fmtR(t.net_r)}R
                    </span>
                  )}
                </div>
                <div className="text-ds-xs text-ink-muted">
                  {fmtTs(t.entry_timestamp)} · {t.leg ?? "—"}
                </div>
              </button>
            );
          })}
        </div>
      </Pane>

      {/* ── Event timeline ── */}
      <Pane
        title={trade ? `Journal · ${trade.trade_ref.slice(-12)}` : "Journal"}
        subtitle={
          trade ? (
            <span className="space-x-1">
              <span>{trade.leg ?? "—"}</span>
              <span>·</span>
              <span>{trade.regime ?? "—"}</span>
            </span>
          ) : null
        }
        right={
          trade?.net_r != null && (
            <Pill tone={trade.net_r >= 0 ? "bull" : "bear"} glow>
              {fmtR(trade.net_r)}R
            </Pill>
          )
        }
        className="col-span-4"
      >
        {!trade ? (
          <div className="px-3 py-10 text-center text-ink-muted text-ds-sm">
            Select a trade
          </div>
        ) : journal.length === 0 ? (
          <div className="px-3 py-10 text-center text-ink-muted text-ds-sm">
            No events
          </div>
        ) : (
          <ol className="relative ml-3 my-2 border-l border-line-subtle">
            {journal.map((e) => (
              <li key={e.event_id} className="relative pl-4 py-1.5 group">
                <span
                  className="absolute -left-[5px] top-2.5 w-2 h-2 rounded-full border border-line-base group-hover:scale-125 transition-transform"
                  style={{ background: gateMarkerColor(e.event_type) }}
                />
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-mono text-ds-xs text-ink-muted">
                    {fmtTs(e.ts).slice(11)}
                  </span>
                  <span className={`text-ds-sm font-medium ${colorForGateStatus(e.event_type)}`}>
                    {shortGateLabel(e.event_type)}
                  </span>
                </div>
                <div className="text-ds-xs text-ink-muted mt-0.5 truncate">
                  {Object.entries(e.detail || {})
                    .filter(([k]) => !["bar_ts", "seq"].includes(k))
                    .slice(0, 4)
                    .map(([k, v]) => `${k}=${stringify(v)}`)
                    .join("  ")}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Pane>

      {/* ── Bar walk ── */}
      <Pane
        title="Bar Walk"
        subtitle={trade ? `${walk.length} bars` : ""}
        className="col-span-6"
      >
        {chartData.length === 0 ? (
          <div className="h-full flex items-center justify-center text-ink-muted text-ds-sm">
            No walk data
          </div>
        ) : (
          <div className="h-full p-2">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData}>
                <defs>
                  <linearGradient id="closeArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#00D26A" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#00D26A" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="ts"
                  tick={{ fontSize: 9, fill: "#5C6470" }}
                  axisLine={{ stroke: "#1F2730" }}
                  tickLine={{ stroke: "#1F2730" }}
                />
                <YAxis
                  tick={{ fontSize: 9, fill: "#5C6470" }}
                  domain={["auto", "auto"]}
                  axisLine={{ stroke: "#1F2730" }}
                  tickLine={{ stroke: "#1F2730" }}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0E1419",
                    border: "1px solid #2A3441",
                    borderRadius: 6,
                    fontSize: 11,
                    color: "#E6EDF3",
                  }}
                  labelStyle={{ color: "#9BA4AE" }}
                />
                {trade && (
                  <>
                    <ReferenceLine
                      y={trade.entry_price}
                      stroke="#9BA4AE"
                      strokeDasharray="2 4"
                      label={{ value: "entry", position: "right", fill: "#9BA4AE", fontSize: 9 }}
                    />
                    <ReferenceLine
                      y={trade.stop_price}
                      stroke="#FF4757"
                      strokeDasharray="2 4"
                      label={{ value: "SL", position: "right", fill: "#FF4757", fontSize: 9 }}
                    />
                    {trade.take_profit_price && (
                      <ReferenceLine
                        y={trade.take_profit_price}
                        stroke="#00D26A"
                        strokeDasharray="2 4"
                        label={{ value: "TP", position: "right", fill: "#00D26A", fontSize: 9 }}
                      />
                    )}
                  </>
                )}
                <Area
                  type="monotone"
                  dataKey="close"
                  stroke="#00D26A"
                  fill="url(#closeArea)"
                  strokeWidth={1.5}
                />
                <Line
                  type="monotone"
                  dataKey="close"
                  stroke="#00D26A"
                  dot={false}
                  strokeWidth={1.5}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Pane>
    </div>
  );
}

function gateMarkerColor(t: string): string {
  if (t === "GATE_SIGNAL_PASSED" || t === "ENTRY_FILL" || t === "EXIT_TP")
    return "#00D26A";
  if (t.startsWith("GATE_PIVOT") || t.startsWith("GATE_SETUP_BUILT"))
    return "#3DAEFF";
  if (t === "ENTRY_SUBMIT") return "#16C784";
  if (t === "EXIT_SL") return "#FF4757";
  if (t === "EXIT_TIMEOUT") return "#FFA02E";
  if (t.startsWith("GATE_")) return "#FF4757";
  return "#9BA4AE";
}

function stringify(v: unknown): string {
  if (v == null) return "null";
  if (typeof v === "number") return Number(v).toFixed(2);
  if (typeof v === "string" && v.length > 24) return v.slice(0, 22) + "…";
  return String(v);
}
