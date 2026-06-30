import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { api, BarWalkRow, JournalEvt, Trade } from "../lib/api";
import { Pane } from "../components/Pane";
import { DataGrid } from "../components/DataGrid";
import { colorForGateStatus, colorForR, fmtPrice, fmtR, fmtTs } from "../lib/format";

export function JournalPage({ runId }: { runId: string | null }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [journal, setJournal] = useState<JournalEvt[]>([]);
  const [walk, setWalk] = useState<BarWalkRow[]>([]);
  const [trade, setTrade] = useState<Trade | null>(null);
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
      setTrade(null);
      return;
    }
    Promise.all([
      api.tradeJournal(tradeId),
      api.tradeBarWalk(tradeId),
    ]).then(([j, w]) => {
      setJournal(j);
      setWalk(w);
    });
    const t = trades.find((x) => x.trade_id === tradeId) ?? null;
    setTrade(t);
  }, [tradeId, trades]);

  const chartData = useMemo(
    () =>
      walk.map((b) => ({
        ts: b.bar_ts.slice(11, 19),
        close: b.close,
        mfe_r: b.mfe_r ?? null,
        mae_r: b.mae_r ?? null,
        unreal: b.unrealised_r ?? null,
      })),
    [walk]
  );

  return (
    <div className="h-full grid grid-cols-12 gap-1">
      <Pane title="Trades" className="col-span-3">
        <DataGrid<Trade>
          rows={trades}
          onRowClick={(t) => setTradeId(t.trade_id)}
          columns={[
            {
              header: "Status",
              cell: (t) => (
                <span
                  className={
                    t.exit_timestamp == null
                      ? "text-term-cyan"
                      : (t.net_r ?? 0) >= 0
                      ? "text-term-green"
                      : "text-term-red"
                  }
                >
                  {t.exit_timestamp == null ? "OPEN" : (t.exit_reason ?? "CLOSED")}
                </span>
              ),
            },
            {
              header: "Side",
              cell: (t) => (
                <span className={t.side > 0 ? "text-term-green" : "text-term-red"}>
                  {t.direction.toUpperCase()}
                </span>
              ),
            },
            { header: "R", cell: (t) => (
              <span className={colorForR(t.net_r)}>{fmtR(t.net_r)}</span>
            ), align: "right" },
            { header: "Entry", cell: (t) => fmtPrice(t.entry_price), align: "right" },
          ]}
        />
      </Pane>

      <Pane
        title={trade ? `Journal · ${trade.trade_ref}` : "Journal"}
        className="col-span-5"
        right={trade && <span>{trade.leg ?? "—"} · {trade.regime ?? "—"}</span>}
      >
        <DataGrid<JournalEvt>
          rows={journal}
          columns={[
            { header: "Time", cell: (e) => fmtTs(e.ts), width: "26%" },
            {
              header: "Event",
              cell: (e) => (
                <span className={colorForGateStatus(e.event_type)}>
                  {e.event_type}
                </span>
              ),
              width: "36%",
            },
            {
              header: "Detail",
              cell: (e) => (
                <span className="text-term-textMuted truncate inline-block max-w-full">
                  {Object.entries(e.detail || {})
                    .slice(0, 5)
                    .map(([k, v]) => `${k}=${stringify(v)}`)
                    .join(" ")}
                </span>
              ),
            },
          ]}
        />
      </Pane>

      <Pane title="Bar Walk" className="col-span-4">
        {chartData.length === 0 ? (
          <div className="p-2 text-term-textMuted">no bars</div>
        ) : (
          <div className="h-full p-1">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData}>
                <XAxis dataKey="ts" tick={{ fontSize: 9, fill: "#aa6620" }} />
                <YAxis tick={{ fontSize: 9, fill: "#aa6620" }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#000", border: "1px solid #FF9933", fontSize: 10 }}
                />
                {trade && (
                  <>
                    <ReferenceLine y={trade.entry_price} stroke="#FF9933" strokeDasharray="2 2" />
                    <ReferenceLine y={trade.stop_price} stroke="#FF3333" strokeDasharray="2 2" />
                    {trade.take_profit_price && (
                      <ReferenceLine y={trade.take_profit_price} stroke="#00CC00" strokeDasharray="2 2" />
                    )}
                  </>
                )}
                <Line type="monotone" dataKey="close" stroke="#FFB347" dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Pane>
    </div>
  );
}

function stringify(v: unknown): string {
  if (v == null) return "null";
  if (typeof v === "number") return Number(v).toFixed(2);
  if (typeof v === "string" && v.length > 20) return v.slice(0, 18) + "…";
  return String(v);
}
