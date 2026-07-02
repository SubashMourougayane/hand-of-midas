import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, BarWalkRow, JournalEvt, Trade } from "../lib/api";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { TradeStory } from "../components/TradeStory";
import { colorForR, fmtR, fmtTs } from "../lib/format";

export function JournalPage({ runId }: { runId: string | null }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [journal, setJournal] = useState<JournalEvt[]>([]);
  const [walk, setWalk] = useState<BarWalkRow[]>([]);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<string>("M5");
  const [search, setSearch] = useSearchParams();

  useEffect(() => {
    if (!runId) return;
    api
      .runDetail(runId)
      .then((d: { run?: { symbol?: string; timeframe?: string } }) => {
        setSymbol(d?.run?.symbol ?? null);
        setTimeframe(d?.run?.timeframe ?? "M5");
      })
      .catch(() => {});
    api.runTrades(runId, undefined, 1, 200).then(({ items }) => {
      setTrades(items);
      const fromQuery = search.get("trade");
      const pick = fromQuery && items.find((t) => t.trade_id === fromQuery);
      if (pick) setTradeId(pick.trade_id);
      else if (items.length > 0) setTradeId(items[0].trade_id);
      else setTradeId(null);
    });
  }, [runId]);

  useEffect(() => {
    if (!tradeId) {
      setJournal([]);
      setWalk([]);
      return;
    }
    let live = true;
    Promise.all([api.tradeJournal(tradeId), api.tradeBarWalk(tradeId)]).then(
      ([j, w]) => {
        if (!live) return;
        setJournal(j);
        setWalk(w);
      }
    );
    return () => {
      live = false;
    };
  }, [tradeId]);

  const trade = useMemo(
    () => trades.find((t) => t.trade_id === tradeId) ?? null,
    [trades, tradeId]
  );

  const selectTrade = (id: string) => {
    setTradeId(id);
    const next = new URLSearchParams(search);
    next.set("trade", id);
    setSearch(next, { replace: true });
  };

  return (
    <div className="h-full grid grid-cols-12 gap-3 p-3 min-h-0">
      {/* ── Left rail: trades list ── */}
      <Pane title="Trades" subtitle={`${trades.length}`} className="col-span-3 xl:col-span-2">
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
                onClick={() => selectTrade(t.trade_id)}
                className={`
                  w-full text-left px-3 py-2 transition-colors duration-ds
                  ${active ? "bg-bg-elevated" : "hover:bg-bg-elevated/60"}
                `}
              >
                <div className="flex items-center gap-2 mb-0.5">
                  <Pill tone={t.side > 0 ? "bull" : "bear"}>
                    {t.direction.toUpperCase()}
                  </Pill>
                  {!closed ? (
                    <Pill tone="info">OPEN</Pill>
                  ) : (
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

      {/* ── Main: trade story ── */}
      <div className="col-span-9 xl:col-span-10 min-h-0 overflow-auto">
        {!trade ? (
          <Pane className="h-full">
            <div className="h-full flex flex-col items-center justify-center gap-2 text-center px-6">
              <span className="text-ink-secondary text-ds-md font-semibold">
                Select a trade to view its story
              </span>
              <span className="text-ink-muted text-ds-sm">
                Pick a trade from the list to see its full lifecycle — geometry,
                annotated bar walk, and the gate-by-gate event timeline.
              </span>
            </div>
          </Pane>
        ) : (
          <TradeStory
            trade={trade}
            journal={journal}
            walk={walk}
            symbol={symbol}
            timeframe={timeframe}
          />
        )}
      </div>
    </div>
  );
}
