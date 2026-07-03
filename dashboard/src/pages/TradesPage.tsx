import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Trade } from "../lib/api";
import { WsEnvelope } from "../lib/ws";
import { legName } from "../lib/labels";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { DataGrid } from "../components/DataGrid";
import { SectionHeader } from "../components/ui/Section";
import { StatTile } from "../components/ui/StatTile";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
import {
  barsToDuration,
  colorForR,
  fmtMoney,
  fmtPriceFor,
  fmtR,
  fmtRiskFor,
  fmtTs,
  tradePnlReal,
} from "../lib/format";

type SortKey = "entry_timestamp" | "net_r" | "bars_held" | "risk_units";

type LivePos = {
  unrealized_usd: number;
  volume: number | null;
  booked_usd: number | null;
  booked_volume: number | null;
};
type WsHook = {
  onMessage: (fn: (env: WsEnvelope) => void) => () => void;
};

export function TradesPage({ runId, ws }: { runId: string | null; ws?: WsHook }) {
  const [rows, setRows] = useState<Trade[]>([]);
  // Live per-ticket unrealised P&L (broker truth) keyed by broker_ticket.
  // Open trades have no realised net_r/broker_net_usd yet — this fills that gap.
  const [livePos, setLivePos] = useState<Record<string, LivePos>>({});
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "entry_timestamp",
    dir: "desc",
  });
  const [symbol, setSymbol] = useState<string | null>(null);
  const [tf, setTf] = useState<string>("M5");
  const nav = useNavigate();

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    (async () => {
      // Resolve the selected run to know if we're in BT or live context.
      let selfRun: any = null;
      try {
        const d: any = await api.runDetail(runId);
        selfRun = d?.run ?? null;
        if (!cancelled) {
          setSymbol(selfRun?.symbol ?? null);
          setTf(selfRun?.timeframe ?? "M5");
        }
      } catch {
        /* ignore */
      }
      const f = filter === "all" ? undefined : filter;
      // LIVE context → merge trades across BOTH legs (long + short share the
      // desk). BT context → just the selected run.
      if (selfRun?.mode === "live") {
        let liveRuns: any[] = [];
        try {
          liveRuns = (await api.runs(100, "live")).filter((r) => !r.end_ts);
        } catch {
          liveRuns = [{ run_id: runId }];
        }
        if (liveRuns.length === 0) liveRuns = [{ run_id: runId }];
        const all = await Promise.all(
          liveRuns.map((r) =>
            api.runTrades(r.run_id, f, 1, 50000).then((x) => x.items).catch(() => [] as Trade[])
          )
        );
        if (!cancelled) setRows(all.flat());
      } else {
        const { items } = await api.runTrades(runId, f, 1, 50000);
        if (!cancelled) setRows(items);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, filter]);

  // Subscribe to live per-ticket unrealised P&L (broker truth via WS).
  useEffect(() => {
    if (!ws) return;
    return ws.onMessage((env) => {
      if (env.channel !== "positions_live") return;
      const positions = (env.payload as any)?.positions as
        | Record<
            string,
            {
              unrealized_usd?: number;
              volume?: number | null;
              booked_usd?: number | null;
              booked_volume?: number | null;
            }
          >
        | undefined;
      if (!positions) return;
      const next: Record<string, LivePos> = {};
      for (const [ticket, p] of Object.entries(positions)) {
        if (typeof p.unrealized_usd === "number") {
          next[ticket] = {
            unrealized_usd: p.unrealized_usd,
            volume: p.volume ?? null,
            booked_usd: typeof p.booked_usd === "number" ? p.booked_usd : null,
            booked_volume: typeof p.booked_volume === "number" ? p.booked_volume : null,
          };
        }
      }
      setLivePos(next);
    });
  }, [ws]);

  const sorted = useMemo(() => {
    const r = [...rows];
    r.sort((a, b) => {
      const av = (a as any)[sort.key];
      const bv = (b as any)[sort.key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (sort.key === "entry_timestamp") {
        const d = new Date(av).getTime() - new Date(bv).getTime();
        return sort.dir === "asc" ? d : -d;
      }
      const d = av - bv;
      return sort.dir === "asc" ? d : -d;
    });
    return r;
  }, [rows, sort]);

  const stats = useMemo(() => {
    const closed = sorted.filter((t) => t.net_r != null);
    const wins = closed.filter((t) => (t.net_r ?? 0) > 0);
    const losses = closed.filter((t) => (t.net_r ?? 0) < 0);
    const netSum = closed.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const winSum = wins.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const lossSum = Math.abs(losses.reduce((s, t) => s + (t.net_r ?? 0), 0));
    const wr = closed.length ? (wins.length / closed.length) * 100 : 0;
    const pf = lossSum > 0 ? winSum / lossSum : winSum > 0 ? Infinity : 0;
    const avg = closed.length ? netSum / closed.length : 0;
    const usd = closed.reduce(
      (s, t) => s + (tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features, t.broker_net_usd) ?? 0),
      0
    );
    return { n: closed.length, wins: wins.length, losses: losses.length, netSum, wr, pf, avg, usd };
  }, [sorted, symbol]);

  const setSortKey = (k: SortKey) =>
    setSort((s) =>
      s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "desc" }
    );

  return (
    <div className="h-full flex flex-col gap-6 px-4 sm:px-6 py-5 min-h-0 w-full">
      {/* ══ SECTION 01 · performance ══ */}
      <section className="flex flex-col gap-3 shrink-0">
        <SectionHeader index="01" title="Performance" question="How is this book doing?" />
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2.5">
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Net R"
              value={fmtR(stats.netSum)}
              tone={stats.netSum >= 0 ? "bull" : "bear"}
              sub={`${stats.n} closed`}
            />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile
              label="$ P&L"
              value={
                stats.usd == null ? "—" : `${stats.usd >= 0 ? "+" : "−"}${Math.abs(stats.usd).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
              }
              unit="USD"
              tone={stats.usd >= 0 ? "bull" : "bear"}
            />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile label="Wins" value={String(stats.wins)} sub={`${stats.losses} losses`} />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile label="Win Rate" value={`${stats.wr.toFixed(1)}`} unit="%" />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Profit Factor"
              value={Number.isFinite(stats.pf) ? stats.pf.toFixed(2) : "∞"}
              tone={stats.pf >= 1 ? "bull" : "bear"}
            />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Avg R"
              value={fmtR(stats.avg, 3)}
              tone={stats.avg >= 0 ? "bull" : "bear"}
            />
          </div>
        </div>
      </section>

      {/* ══ SECTION 02 · trade ledger ══ */}
      <SectionHeader
        index="02"
        title="Trade Ledger"
        question={`${sorted.length} loaded`}
        right={
          <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
            <TabsList>
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="open">Open</TabsTrigger>
              <TabsTrigger value="closed">Closed</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />
      <Pane className="flex-1 min-h-0">
        <DataGrid<Trade>
          rows={sorted}
          rowKey={(t) => t.trade_id}
          onRowClick={(t) => nav(`/journal?trade=${t.trade_id}`)}
          columns={[
            {
              header: "Status",
              cell: (t) =>
                t.exit_timestamp == null ? (
                  <Pill tone="info">OPEN</Pill>
                ) : (
                  <Pill
                    tone={
                      t.exit_reason === "TP" || (t.net_r ?? 0) >= 0
                        ? "bull"
                        : t.exit_reason === "SL"
                        ? "bear"
                        : "warn"
                    }
                  >
                    {t.exit_reason ?? "CLOSED"}
                  </Pill>
                ),
            },
            {
              header: "Strategy",
              cell: (t) => (
                <Pill tone={t.side > 0 ? "bull" : "bear"}>
                  {legName(t.leg)}
                </Pill>
              ),
            },
            {
              header: "Ticket",
              cell: (t) => (
                <span className="font-mono text-ds-xs text-ink-secondary">
                  {t.broker_ticket || "—"}
                </span>
              ),
            },
            {
              header: sortHeader("Entry", "entry_timestamp", sort, setSortKey),
              cell: (t) => (
                <span className="font-mono text-ds-xs text-ink-secondary">
                  {fmtTs(t.entry_timestamp)}
                </span>
              ),
            },
            {
              header: "Entry",
              cell: (t) => (
                <span className="font-mono">{fmtPriceFor(symbol, t.entry_price)}</span>
              ),
              align: "right",
            },
            {
              header: "Exit",
              cell: (t) => (
                <span className="font-mono text-ink-secondary">
                  {fmtPriceFor(symbol, t.exit_price)}
                </span>
              ),
              align: "right",
            },
            {
              header: "SL",
              cell: (t) => (
                <span className="font-mono text-ds-xs text-bear/80">
                  {fmtPriceFor(symbol, t.stop_price)}
                </span>
              ),
              align: "right",
            },
            {
              header: "TP",
              cell: (t) => (
                <span className="font-mono text-ds-xs text-bull/80">
                  {fmtPriceFor(symbol, t.take_profit_price)}
                </span>
              ),
              align: "right",
            },
            {
              header: sortHeader("Risk", "risk_units", sort, setSortKey),
              cell: (t) => (
                <span className="font-mono text-ds-xs text-ink-secondary">
                  {fmtRiskFor(symbol, t.risk_units)}
                </span>
              ),
              align: "right",
            },
            {
              header: sortHeader("Held", "bars_held", sort, setSortKey),
              cell: (t) => (
                <span className="font-mono text-ink-secondary">
                  {barsToDuration(t.bars_held, tf)}
                </span>
              ),
              align: "right",
            },
            {
              header: "Partial",
              cell: (t) =>
                t.partial_taken ? (
                  <Pill tone="bull">
                    {`PTP +${(t.partial_r ?? 0).toFixed(2)}R`}
                  </Pill>
                ) : (
                  <span className="text-ink-muted">—</span>
                ),
            },
            {
              header: sortHeader("Net R", "net_r", sort, setSortKey),
              cell: (t) => (
                <span className={`font-mono ${colorForR(t.net_r)}`}>
                  {fmtR(t.net_r)}
                </span>
              ),
              align: "right",
            },
            {
              header: "$ PnL",
              cell: (t) => {
                const realized = tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features, t.broker_net_usd);
                // OPEN trade with no realised P&L → show live floating $ (broker truth via WS).
                const isOpen = t.exit_timestamp == null;
                const live = t.broker_ticket ? livePos[t.broker_ticket] : undefined;
                if (isOpen && realized == null && live) {
                  const hasBooked =
                    live.booked_usd != null && Math.abs(live.booked_usd) > 0.001;
                  return (
                    <div className="flex flex-col items-end leading-tight">
                      {hasBooked && (
                        <span
                          className={`font-mono ${colorForR(live.booked_usd)}`}
                          title="Realised P&L already locked from the partial-TP close (fixed)."
                        >
                          {fmtMoney(live.booked_usd, 0)}
                          <span className="ml-1 text-ds-xs text-ink-muted uppercase">booked</span>
                        </span>
                      )}
                      <span
                        className={`font-mono font-semibold ${colorForR(live.unrealized_usd)}`}
                        title="Indicative floating P&L on the still-open remainder (1s tick feed). Exact broker P&L written on close."
                      >
                        ~{fmtMoney(live.unrealized_usd, 0)}
                        <span className="ml-1 text-ds-xs text-ink-muted uppercase">float</span>
                      </span>
                    </div>
                  );
                }
                return (
                  <span className={`font-mono font-semibold ${colorForR(realized)}`}>
                    {fmtMoney(realized, 0)}
                  </span>
                );
              },
              align: "right",
            },
          ]}
        />
      </Pane>
    </div>
  );
}

function sortHeader(
  label: string,
  key: SortKey,
  sort: { key: SortKey; dir: "asc" | "desc" },
  setSortKey: (k: SortKey) => void
) {
  const active = sort.key === key;
  return (
    <button
      onClick={() => setSortKey(key)}
      className={`inline-flex items-center gap-1 transition-colors ${
        active ? "text-ink-primary" : "text-ink-muted hover:text-ink-secondary"
      }`}
    >
      {label}
      {active && (
        <span className="text-bull">
          {sort.dir === "asc" ? "↑" : "↓"}
        </span>
      )}
    </button>
  );
}
