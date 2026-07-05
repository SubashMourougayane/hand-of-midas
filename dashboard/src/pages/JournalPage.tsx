import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, BarWalkRow, JournalEvt, Trade } from "../lib/api";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { TradeStory } from "../components/TradeStory";
import { SectionHeader } from "../components/ui/Section";
import { colorForR, fmtR, fmtTs } from "../lib/format";
import { legName, sideLabel } from "../lib/labels";

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
    let cancelled = false;
    (async () => {
      let selfRun: any = null;
      try {
        const d: any = await api.runDetail(runId);
        selfRun = d?.run ?? null;
        if (!cancelled) {
          setSymbol(selfRun?.symbol ?? null);
          setTimeframe(selfRun?.timeframe ?? "M5");
        }
      } catch {
        /* ignore */
      }
      // LIVE → merge both legs' trades so long + short both show.
      let items: Trade[] = [];
      if (selfRun?.mode === "live") {
        let liveRuns: any[] = [];
        try {
          liveRuns = (await api.runs(100, "live")).filter((r) => !r.end_ts);
        } catch {
          liveRuns = [{ run_id: runId }];
        }
        if (liveRuns.length === 0) liveRuns = [{ run_id: runId }];
        const all = await Promise.all(
          liveRuns.map((r) => api.runTrades(r.run_id, undefined, 1, 200).then((x) => x.items).catch(() => [] as Trade[]))
        );
        items = all.flat().sort(
          (a, b) => new Date(b.entry_timestamp).getTime() - new Date(a.entry_timestamp).getTime()
        );
      } else {
        items = (await api.runTrades(runId, undefined, 1, 200)).items;
      }
      if (cancelled) return;
      setTrades(items);
      const fromQuery = search.get("trade");
      const pick = fromQuery && items.find((t) => t.trade_id === fromQuery);
      if (pick) setTradeId(pick.trade_id);
      else if (items.length > 0) setTradeId(items[0].trade_id);
      else setTradeId(null);
    })();
    return () => {
      cancelled = true;
    };
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
    <div className="h-full flex flex-col gap-4 px-4 sm:px-6 py-5 min-h-0 w-full overflow-auto">
      <SectionHeader index="01" title="Trade Journal" question="What happened, bar by bar?" />
      {/* Mobile: list stacks above the story. Desktop: list is a left rail. */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-3 min-h-0">
      {/* ── Left rail: trades list ── */}
      <Pane title="Trades" subtitle={`${trades.length}`} className="lg:col-span-3 xl:col-span-2 max-h-[40vh] lg:max-h-none overflow-auto">
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
                    {sideLabel(t.side)}
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
                  {fmtTs(t.entry_timestamp)} · {legName(t.leg)}
                </div>
              </button>
            );
          })}
        </div>
      </Pane>

      {/* ── Main: trade story ── */}
      <div className="lg:col-span-9 xl:col-span-10 min-h-0 overflow-auto">
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
    </div>
  );
}
