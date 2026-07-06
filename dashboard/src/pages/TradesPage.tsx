import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Trade } from "../lib/api";
import { WsEnvelope, useWsLive } from "../lib/ws";
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

export function TradesPage({ runId }: { runId: string | null; ws?: WsHook }) {
  const [rows, setRows] = useState<Trade[]>([]);
  // Live per-ticket unrealised P&L (broker truth) keyed by broker_ticket.
  // Open trades have no realised net_r/broker_net_usd yet — this fills that gap.
  const [livePos, setLivePos] = useState<Record<string, LivePos>>({});
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  // Client-side refinements applied on top of the loaded rows.
  const [sideFilter, setSideFilter] = useState<"all" | "long" | "short">("all");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "entry_timestamp",
    dir: "desc",
  });
  const [symbol, setSymbol] = useState<string | null>(null);
  const [tf, setTf] = useState<string>("M5");
  const nav = useNavigate();
  // Floating P&L feed: positions_live is ACCOUNT-WIDE (run_id=null). The App ws is
  // run-scoped and doesn't deliver it here, so open the same account-wide socket
  // LivePage uses. This is why the cockpit showed floating but the ledger didn't.
  const acctWs = useWsLive(null);

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
        // Merge trades across ALL live runs of the CURRENTLY-live strategies
        // (ended runs included — restarts create new run rows, but their closed
        // trades still belong to the book). Scope by the strategy_ids that have
        // an active run so retired experiments (sdr001…) stay excluded.
        let liveRuns: any[] = [];
        try {
          const allLive = await api.runs(200, "live");
          const activeStrats = new Set(
            allLive.filter((r) => !r.end_ts).map((r) => r.strategy_id)
          );
          liveRuns = activeStrats.size
            ? allLive.filter((r) => activeStrats.has(r.strategy_id))
            : allLive;
        } catch {
          liveRuns = [{ run_id: runId }];
        }
        if (liveRuns.length === 0) liveRuns = [{ run_id: runId }];
        const all = await Promise.all(
          liveRuns.map((r) =>
            api.runTrades(r.run_id, f, 1, 50000).then((x) => x.items).catch(() => [] as Trade[])
          )
        );
        // Collapse to ONE row per real position. The A+D dual-run adoption
        // creates TWO trade_ids for the same broker ticket, so dedup by
        // broker_ticket (not trade_id). Prefer the richest row (has partial /
        // broker $). Rows with NO broker_ticket fall back to trade_id dedup.
        // Drop RECONCILED_FLAT phantoms (never-filled cutover artifacts).
        const flat = all.flat().filter(
          (t) => t.exit_reason !== "RECONCILED_FLAT" && t.exit_reason !== "RECON_PENDING"
        );
        const byTicket = new Map<string, Trade>();
        const noTicket: Trade[] = [];
        const seenTid = new Set<string>();
        for (const t of flat) {
          const tk = (t.broker_ticket ?? "").trim();
          if (!tk) {
            if (!seenTid.has(t.trade_id)) { seenTid.add(t.trade_id); noTicket.push(t); }
            continue;
          }
          const cur = byTicket.get(tk);
          if (!cur) { byTicket.set(tk, t); continue; }
          // Keep the richest row: prefer real booked $ (raw_features), then a
          // set partial_r, then broker_net_usd, then partial_taken. The A+D
          // dual-adopt writes 2 rows/ticket and only ONE carries the full
          // partial detail.
          const score = (x: Trade) => {
            const booked = Number(
              (x.raw_features as Record<string, unknown> | null)?.["partial_booked_usd"]
            );
            return (
              // MT5 truth first: a row the broker STILL holds beats a stale
              // SUPERSEDED/closed duplicate for the same ticket (fixes the
              // cockpit-open / trades-SUPERSEDED disagreement).
              (x.broker_open === true ? 16 : 0) +
              (Number.isFinite(booked) && Math.abs(booked) > 0.001 ? 8 : 0) +
              (x.partial_r ? Math.abs(x.partial_r) : 0) +
              (x.broker_net_usd != null ? 1 : 0) +
              (x.partial_taken ? 0.5 : 0)
            );
          };
          if (score(t) > score(cur)) byTicket.set(tk, t);
        }
        const merged = [...byTicket.values(), ...noTicket];
        if (!cancelled) setRows(merged);
      } else {
        const { items } = await api.runTrades(runId, f, 1, 50000);
        if (!cancelled) setRows(items);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, filter]);

  // Subscribe to live per-ticket unrealised P&L (broker truth via WS). Use the
  // account-wide socket (acctWs) — positions_live is not run-scoped.
  useEffect(() => {
    return acctWs.onMessage((env) => {
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
  }, [acctWs]);

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

  // Client-side refinements (side / date range / ticket search) on top of the
  // loaded + sorted rows. KPIs + grid both consume this filtered set.
  const filtered = useMemo(() => {
    const fromT = fromDate ? new Date(fromDate).getTime() : null;
    const toT = toDate ? new Date(toDate).getTime() + 86_400_000 : null; // inclusive end-of-day
    const q = search.trim().toLowerCase();
    return sorted.filter((t) => {
      if (sideFilter === "long" && t.side <= 0) return false;
      if (sideFilter === "short" && t.side >= 0) return false;
      if (fromT != null || toT != null) {
        const et = t.entry_timestamp ? new Date(t.entry_timestamp).getTime() : null;
        if (et == null) return false;
        if (fromT != null && et < fromT) return false;
        if (toT != null && et >= toT) return false;
      }
      if (q) {
        const hay = `${t.broker_ticket ?? ""} ${legName(t.leg)} ${t.exit_reason ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [sorted, sideFilter, fromDate, toDate, search]);

  const stats = useMemo(() => {
    // A trade counts as CLOSED for KPIs only if the broker no longer holds it.
    // MT5 truth: broker_open===true (or null-unknown + still open) must NOT be
    // booked as a realised result — it's a live float.
    const isBrokerOpen = (t: Trade) =>
      t.broker_open === true || (t.broker_open == null && t.exit_timestamp == null);
    // CLOSED = broker done with it AND it has SOME realised result (net_r OR a
    // reconciled broker_net_usd). Broker-closed rows (H1 intrabar close) have
    // net_r=null but a real broker_net_usd — they were previously dropped from
    // BOTH KPIs while still showing in the ledger, so Net R and $ P&L counted
    // different sets and disagreed. Now the $ set includes them.
    const closed = filtered.filter(
      (t) => !isBrokerOpen(t) && (t.net_r != null || t.broker_net_usd != null)
    );
    // R-metrics only make sense on rows that carry an R value; reconciled
    // broker-closed rows (no net_r) contribute $ but are excluded from R math.
    const withR = closed.filter((t) => t.net_r != null);
    const wins = withR.filter((t) => (t.net_r ?? 0) > 0);
    const losses = withR.filter((t) => (t.net_r ?? 0) < 0);
    const netSum = withR.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const winSum = wins.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const lossSum = Math.abs(losses.reduce((s, t) => s + (t.net_r ?? 0), 0));
    const wr = withR.length ? (wins.length / withR.length) * 100 : 0;
    const pf = lossSum > 0 ? winSum / lossSum : winSum > 0 ? Infinity : 0;
    const avg = withR.length ? netSum / withR.length : 0;
    // $ P&L counts EVERY closed row (incl. reconciled broker-closed) so it ties
    // to the ledger's visible $ column and to the account balance move.
    const usd = closed.reduce(
      (s, t) => s + (tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features, t.broker_net_usd, t.broker_ticket) ?? 0),
      0
    );
    // Add realised $ ALREADY BOOKED on still-open trades (partial-TP). Prefer
    // live WS booked, else the DB raw_features fallback. This is locked profit,
    // so it belongs in the $ P&L total even while the remainder floats.
    const openBooked = filtered
      .filter((t) => isBrokerOpen(t))
      .reduce((s, t) => {
        const live = t.broker_ticket ? livePos[t.broker_ticket] : undefined;
        const dbBooked = Number(
          (t.raw_features as Record<string, unknown> | null)?.["partial_booked_usd"]
        );
        const booked =
          live?.booked_usd != null && Math.abs(live.booked_usd) > 0.001
            ? live.booked_usd
            : Number.isFinite(dbBooked)
            ? dbBooked
            : 0;
        return s + booked;
      }, 0);
    return { n: closed.length, nR: withR.length, wins: wins.length, losses: losses.length, netSum, wr, pf, avg, usd: usd + openBooked };
  }, [filtered, symbol, livePos]);

  const setSortKey = (k: SortKey) =>
    setSort((s) =>
      s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "desc" }
    );

  return (
    <div className="h-full overflow-y-auto flex flex-col gap-6 px-4 sm:px-6 py-5 min-h-0 w-full">
      {/* ══ SECTION 01 · performance ══ */}
      <section className="flex flex-col gap-3 shrink-0">
        <SectionHeader index="01" title="Performance" question="How is this book doing?" />
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2.5">
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Net R"
              value={fmtR(stats.netSum)}
              tone={stats.netSum >= 0 ? "bull" : "bear"}
              sub={`${stats.nR} scored · ${stats.n} closed`}
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
        question={`${filtered.length} of ${sorted.length}`}
      />
      {/* ONE cohesive filter bar: status · side · date range · search. All
          filter-aware — KPIs + table recompute together. */}
      <div className="flex flex-wrap items-center gap-2 shrink-0">
        <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="open">Open</TabsTrigger>
            <TabsTrigger value="closed">Closed</TabsTrigger>
          </TabsList>
        </Tabs>
        <span className="w-px h-5 bg-glass-border mx-0.5" />
        <Tabs value={sideFilter} onValueChange={(v) => setSideFilter(v as typeof sideFilter)}>
          <TabsList>
            <TabsTrigger value="all">Both</TabsTrigger>
            <TabsTrigger value="long">Long</TabsTrigger>
            <TabsTrigger value="short">Short</TabsTrigger>
          </TabsList>
        </Tabs>
        <span className="w-px h-5 bg-glass-border mx-0.5" />
        <input
          type="date"
          value={fromDate}
          onChange={(e) => setFromDate(e.target.value)}
          className="glass rounded-ds-sm px-2 py-1 text-ds-xs font-mono text-ink-secondary bg-transparent border border-glass-border"
          title="From date (entry)"
        />
        <span className="text-ink-dim text-ds-xs">→</span>
        <input
          type="date"
          value={toDate}
          onChange={(e) => setToDate(e.target.value)}
          className="glass rounded-ds-sm px-2 py-1 text-ds-xs font-mono text-ink-secondary bg-transparent border border-glass-border"
          title="To date (entry)"
        />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="search ticket / side / reason…"
          className="glass rounded-ds-sm px-2 py-1 text-ds-xs text-ink-secondary bg-transparent border border-glass-border flex-1 min-w-[160px]"
        />
        {(filter !== "all" || sideFilter !== "all" || fromDate || toDate || search) && (
          <button
            onClick={() => { setFilter("all"); setSideFilter("all"); setFromDate(""); setToDate(""); setSearch(""); }}
            className="text-ds-xs text-ink-muted hover:text-ink-primary underline"
          >
            clear
          </button>
        )}
      </div>
      <Pane className="flex-1 min-h-[50vh] lg:min-h-0 overflow-auto">
        <DataGrid<Trade>
          rows={filtered}
          rowKey={(t) => t.trade_id}
          onRowClick={(t) => nav(`/journal?trade=${t.trade_id}`)}
          columns={[
            {
              header: "Status",
              // MT5 is the source of truth for open/closed:
              //  - broker_open === true  → OPEN (even if a stale DB row says SUPERSEDED/closed)
              //  - broker_open === false → closed at broker (show the exit reason if any)
              //  - broker_open == null   → unknown → trust DB (exit_timestamp)
              cell: (t) => {
                const isOpen =
                  t.broker_open === true ||
                  (t.broker_open == null && t.exit_timestamp == null);
                if (isOpen) return <Pill tone="info">OPEN</Pill>;
                return (
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
                );
              },
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
              cell: (t) => {
                // Broker-open (MT5 truth) → no realised R yet even if a stale DB row
                // carries net_r (SUPERSEDED re-adopt). Show — (floating shown in $ PnL).
                const stillOpen =
                  t.broker_open === true ||
                  (t.broker_open == null && t.exit_timestamp == null);
                return (
                  <span className={`font-mono ${colorForR(stillOpen ? null : t.net_r)}`}>
                    {stillOpen ? "—" : fmtR(t.net_r)}
                  </span>
                );
              },
              align: "right",
            },
            {
              header: "$ PnL",
              cell: (t) => {
                const realized = tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features, t.broker_net_usd, t.broker_ticket);
                // OPEN trade → show live floating $ (broker truth via WS). MT5 is the
                // source of truth: broker_open===true means the position is open even
                // if a stale DB row carries an exit_timestamp (SUPERSEDED re-adopt).
                const isOpen =
                  t.broker_open === true ||
                  (t.broker_open == null && t.exit_timestamp == null);
                const live = t.broker_ticket ? livePos[t.broker_ticket] : undefined;
                // Broker-open → floating wins even if a stale DB row has a realised
                // net_r (SUPERSEDED re-adopt). Otherwise keep the "no realised yet" gate.
                if (isOpen && live && (realized == null || t.broker_open === true)) {
                  // Prefer live WS booked $; fall back to DB raw_features
                  // partial_booked_usd (for trades whose partial deal aged off
                  // the DWX buffer, e.g. pre-cutover).
                  const dbBooked = Number(
                    (t.raw_features as Record<string, unknown> | null)?.["partial_booked_usd"]
                  );
                  const bookedVal =
                    live.booked_usd != null && Math.abs(live.booked_usd) > 0.001
                      ? live.booked_usd
                      : Number.isFinite(dbBooked) && Math.abs(dbBooked) > 0.001
                      ? dbBooked
                      : null;
                  const hasBooked = bookedVal != null;
                  return (
                    <div className="flex flex-col items-end leading-tight">
                      {hasBooked && (
                        <span
                          className={`font-mono ${colorForR(bookedVal)}`}
                          title="Realised P&L already locked from the partial-TP close (fixed)."
                        >
                          {fmtMoney(bookedVal!, 0)}
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
                // Broker-closed but $ not yet reconciled (deal aged off the DWX
                // buffer before USD backfill): show "pending" not the 1.0-lot fantasy.
                if (realized == null && t.broker_ticket) {
                  return (
                    <span
                      className="font-mono text-ink-muted"
                      title="Broker-closed; exact $ P&L pending reconcile (deal aged off the DWX buffer). R is scored; $ backfills from MT5 History."
                    >
                      — <span className="text-ds-xs uppercase">pending</span>
                    </span>
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
