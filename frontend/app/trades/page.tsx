"use client";
import { useEffect, useMemo, useState } from "react";
import TradeJourney from "@/components/TradeJourney";
import { formatINR } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import { client, type ServiceKey } from "@/lib/client";
import {
  PageHeader,
  Card,
  Stat,
  Tabs,
  Table,
  Badge,
  Button,
  Sheet,
  EmptyState,
  type Column,
} from "@/components/ui";

interface LiveTrade {
  trade_ref: string; strategy: string; side: string;
  entry_time: string; exit_time: string; entry_price: number;
  exit_price: number; sl: number; tp: number; units: number;
  pnl_gbp: number; pnl_usd: number; exit_reason: string; mode: string;
}

interface BacktestTrade {
  date: string; year: number; strategy: string; direction: string;
  entry: number; sl: number; tp: number; exit_price: number;
  pnl_sized: number; units: number; status: string; hold_human: string;
  risk: number; r_mult: number; equity_after: number; bars_held?: number;
}

interface Stats {
  total?: number;
  win_rate?: number;
  total_pnl?: number;
  avg_win?: number;
  avg_loss?: number;
}

const PER_PAGE = 50;

const STRATEGY_META: Record<string, { label: string; color: string }> = {
  alpha_sweep: { label: "Alpha", color: "var(--color-info)" },
  micro_alpha_sweep: { label: "Alpha", color: "var(--color-info)" },
  micro_alpha_sweep_oil: { label: "Alpha", color: "var(--color-info)" },
  mean_rev: { label: "MRev", color: "var(--color-win)" },
  cross_market: { label: "Cross", color: "var(--color-warn)" },
};

function strategyBadge(strategy: string) {
  const key = Object.keys(STRATEGY_META).find((k) => strategy.includes(k)) ?? "cross_market";
  const meta = STRATEGY_META[key];
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: meta.color }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} aria-hidden />
      {meta.label}
    </span>
  );
}

function formatLiveDate(iso?: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
}

function formatBacktestDate(iso: string) {
  // "2006-04-13T21:00:00+00:00" -> "13 Apr 2006"
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function TradesPage() {
  const { instrument } = useInstrument();
  const svc = instrument as ServiceKey;
  const [tab, setTab] = useState<"live" | "backtest">("backtest");
  // O2: exitReason filter is client-side (live tab) for filter27 lifecycle events.
  // Not part of backend params — filters the rendered list post-fetch.
  const [filter, setFilter] = useState({ strategy: "", side: "", result: "", year: "", exitReason: "" });
  const [page, setPage] = useState(1);
  const [liveTrades, setLiveTrades] = useState<LiveTrade[]>([]);
  const [btTrades, setBtTrades] = useState<BacktestTrade[]>([]);
  const [stats, setStats] = useState<Stats>({});
  const [totalPages, setTotalPages] = useState(1);
  const [totalTrades, setTotalTrades] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<BacktestTrade | LiveTrade | null>(null);

  // Reset to page 1 whenever the underlying query changes
  useEffect(() => { setPage(1); }, [filter, tab, instrument]);

  // Fetch
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      const params: Record<string, unknown> = {};
      if (filter.strategy) {
        params.strategy = filter.strategy === "alpha_sweep" ? "micro_alpha_sweep" : filter.strategy;
      }
      if (filter.side) params.side = filter.side;
      if (filter.result) params.result = filter.result.toUpperCase();
      try {
        if (tab === "live") {
          params.limit = 200;
          const data = await client(svc).trades<{ trades?: LiveTrade[]; stats?: Stats }>({ ...params });
          if (cancelled) return;
          setLiveTrades(Array.isArray(data) ? data as LiveTrade[] : (data?.trades ?? []));
          setStats(((data as { stats?: Stats })?.stats ?? {}) as Stats);
        } else {
          params.source = "backtest";
          if (filter.year) params.year = filter.year;
          params.page = page;
          params.per_page = PER_PAGE;
          const data = await client(svc).trades<{ trades?: BacktestTrade[]; stats?: Stats; pages?: number; total?: number }>({ ...params });
          if (cancelled) return;
          setBtTrades(data?.trades ?? []);
          setTotalPages(data?.pages ?? 1);
          setTotalTrades(data?.total ?? 0);
          setStats((data?.stats ?? {}) as Stats);
        }
      } catch {
        if (!cancelled) {
          setLiveTrades([]);
          setBtTrades([]);
          setStats({});
        }
      }
      if (!cancelled) setLoading(false);
    };
    run();
    return () => { cancelled = true; };
  }, [tab, filter, page, svc]);

  // Close detail sheet when service changes (data is now stale)
  useEffect(() => { setSelected(null); }, [svc]);

  const liveCols: Column<LiveTrade>[] = useMemo(() => [
    {
      key: "date",
      header: "When",
      cell: (t) => <span className="num text-[var(--color-text-muted)]">{formatLiveDate(t.exit_time || t.entry_time)}</span>,
    },
    { key: "strategy", header: "Strategy", cell: (t) => strategyBadge(t.strategy) },
    {
      key: "mode",
      header: "Mode",
      // O2: pending vs live distinction. Filled (live) = empty so it doesn't
      // clutter every row; pending = subdued PENDING badge so operator can
      // skim "did this fill or not?". Both Micros (the only live systems
      // post-2026-06-19) populate the field via Filter #27 limit-order pre-walk.
      cell: (t) => (
        t.mode === "pending" ? (
          <span className="px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider rounded border border-[var(--color-border)] text-[var(--color-text-dim)]">
            PENDING
          </span>
        ) : <span className="text-[var(--color-text-dim)] text-[11px]">—</span>
      ),
      hideOnMobile: true,
    },
    {
      key: "side",
      header: "Side",
      cell: (t) => <Badge tone={t.side === "LONG" ? "win" : "loss"} variant="soft">{t.side}</Badge>,
    },
    {
      key: "entry",
      header: "Entry",
      align: "right",
      cell: (t) => <span className="num">${t.entry_price.toFixed(2)}</span>,
    },
    {
      key: "exit",
      header: "Exit",
      align: "right",
      cell: (t) => <span className="num text-[var(--color-text-dim)]">{t.exit_price ? `$${t.exit_price.toFixed(2)}` : "—"}</span>,
    },
    {
      key: "pnl",
      header: "P&L",
      align: "right",
      cell: (t) => {
        const v = t.pnl_usd ?? t.pnl_gbp ?? 0;
        return (
          <span className={`num font-semibold ${v >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
            {v >= 0 ? "+" : ""}{v.toFixed(0)}
          </span>
        );
      },
    },
    {
      key: "exitReason",
      header: "Reason",
      cell: (t) => <span className="text-[11px] text-[var(--color-warn)] uppercase">{t.exit_reason ?? "—"}</span>,
      hideOnMobile: true,
    },
    {
      key: "units",
      header: "Units",
      align: "right",
      cell: (t) => <span className="num text-[var(--color-text-dim)]">{t.units}</span>,
      hideOnMobile: true,
    },
  ], []);

  const btCols: Column<BacktestTrade>[] = useMemo(() => [
    {
      key: "date",
      header: "Date",
      cell: (t) => <span className="num text-[var(--color-text-muted)]">{formatBacktestDate(t.date)}</span>,
    },
    { key: "strategy", header: "Strategy", cell: (t) => strategyBadge(t.strategy) },
    {
      key: "side",
      header: "Side",
      cell: (t) => <Badge tone={t.direction === "LONG" ? "win" : "loss"} variant="soft">{t.direction}</Badge>,
    },
    {
      key: "entry",
      header: "Entry",
      align: "right",
      cell: (t) => <span className="num">${t.entry.toFixed(0)}</span>,
    },
    {
      key: "exit",
      header: "Exit",
      align: "right",
      cell: (t) => <span className="num text-[var(--color-text-dim)]">${t.exit_price.toFixed(0)}</span>,
    },
    {
      key: "pnl",
      header: "P&L",
      align: "right",
      cell: (t) => (
        <span className={`num font-semibold ${t.pnl_sized >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
          {t.pnl_sized >= 0 ? "+" : ""}${t.pnl_sized.toFixed(0)}
        </span>
      ),
    },
    {
      key: "r",
      header: "R",
      align: "right",
      cell: (t) => (
        <span
          className={`num text-[11px] ${
            t.r_mult > 0 ? "text-[var(--color-win)]" : t.r_mult < 0 ? "text-[var(--color-loss)]" : "text-[var(--color-text-muted)]"
          }`}
        >
          {t.r_mult > 0 ? "+" : ""}{t.r_mult.toFixed(1)}R
        </span>
      ),
      hideOnMobile: true,
    },
    {
      key: "exitReason",
      header: "Exit",
      cell: (t) => <span className="text-[11px] text-[var(--color-warn)] uppercase">{t.status}</span>,
      hideOnMobile: true,
    },
    {
      key: "hold",
      header: "Held",
      cell: (t) => <span className="text-[11px] text-[var(--color-text-dim)]">{t.hold_human}</span>,
      hideOnMobile: true,
    },
  ], []);

  // Type-narrowing for the Sheet content
  const selectedBacktest = selected && "pnl_sized" in selected ? selected as BacktestTrade : null;

  const totalPnl = stats.total_pnl ?? 0;

  return (
    <div className="p-3 sm:p-6 max-w-[1280px] mx-auto">
      <PageHeader
        title="Trades"
        description="Live execution and backtested results"
        actions={
          <Tabs.Root value={tab} onValueChange={(v) => setTab(v as "live" | "backtest")}>
            <Tabs.List>
              <Tabs.Trigger value="live">Live</Tabs.Trigger>
              <Tabs.Trigger value="backtest">Backtest</Tabs.Trigger>
            </Tabs.List>
          </Tabs.Root>
        }
      />

      {/* Filter bar */}
      <Card padded surface={1} className="mb-4">
        <div className="flex gap-2 flex-wrap items-center">
          <select
            value={filter.strategy}
            onChange={(e) => setFilter({ ...filter, strategy: e.target.value })}
            aria-label="Filter by strategy"
          >
            <option value="">All Strategies</option>
            <option value="alpha_sweep">Alpha-Sweep</option>
            <option value="micro_alpha_sweep">Micro Alpha-Sweep</option>
            <option value="mean_rev">Mean-Rev</option>
            <option value="cross_market">Cross-Market</option>
          </select>
          <select
            value={filter.side}
            onChange={(e) => setFilter({ ...filter, side: e.target.value })}
            aria-label="Filter by side"
          >
            <option value="">All Sides</option>
            <option value="LONG">Long</option>
            <option value="SHORT">Short</option>
          </select>
          <select
            value={filter.result}
            onChange={(e) => setFilter({ ...filter, result: e.target.value })}
            aria-label="Filter by result"
          >
            <option value="">All Results</option>
            <option value="WIN">Winners</option>
            <option value="LOSS">Losers</option>
          </select>
          {tab === "backtest" ? (
            <select
              value={filter.year}
              onChange={(e) => setFilter({ ...filter, year: e.target.value })}
              aria-label="Filter by year"
            >
              <option value="">All Years</option>
              {Array.from({ length: 21 }, (_, i) => 2006 + i).map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          ) : null}
          {tab === "live" ? (
            // O2: filter live trades by Filter #27 lifecycle exit reason — quickly
            // surface "fill rate of last 100 limits", "any orphans?", etc.
            <select
              value={filter.exitReason}
              onChange={(e) => setFilter({ ...filter, exitReason: e.target.value })}
              aria-label="Filter by exit reason"
            >
              <option value="">All Reasons</option>
              <option value="LIMIT_TTL_EXPIRED">Limit TTL Expired (clean)</option>
              <option value="LIMIT_TTL_EXPIRED_GRACE">Limit TTL Expired (grace fallback)</option>
              <option value="LIMIT_BAD_OPEN_PRICE_FORCE_CANCELLED">Bad open_price force-cancelled</option>
              <option value="MANUAL_CLOSE_WEB">Manual close (web)</option>
              <option value="STOP_LOSS">Stop loss</option>
              <option value="TAKE_PROFIT">Take profit</option>
            </select>
          ) : null}
          {(filter.strategy || filter.side || filter.result || filter.year || filter.exitReason) ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setFilter({ strategy: "", side: "", result: "", year: "", exitReason: "" })}
            >
              Reset
            </Button>
          ) : null}
        </div>
      </Card>

      {/* Stats row */}
      {stats.total && stats.total > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mb-4 hom-stagger-children">
          <Card padded lift className="hom-stagger">
            <Stat label="Trades" value={stats.total} animate mono />
          </Card>
          <Card padded lift className="hom-stagger">
            <Stat
              label="Win rate"
              value={(stats.win_rate ?? 0) * 100}
              animate
              decimals={1}
              suffix="%"
              tone={(stats.win_rate ?? 0) > 0.5 ? "win" : "neutral"}
            />
          </Card>
          <Card padded lift className="hom-stagger">
            <Stat
              label="Total P&L"
              value={totalPnl}
              animate
              prefix={totalPnl >= 0 ? "+$" : "-$"}
              decimals={0}
              tone={totalPnl >= 0 ? "win" : "loss"}
              hint={<span className="num">{formatINR(totalPnl)}</span>}
            />
          </Card>
          <Card padded lift className="hom-stagger">
            <Stat
              label="Avg win"
              value={stats.avg_win ?? 0}
              animate
              prefix="+$"
              tone="win"
              hint={<span className="num">{formatINR(stats.avg_win ?? 0)}</span>}
            />
          </Card>
          <Card padded lift className="hom-stagger">
            <Stat
              label="Avg loss"
              value={Math.abs(stats.avg_loss ?? 0)}
              animate
              prefix="-$"
              tone="loss"
              hint={<span className="num">{formatINR(stats.avg_loss ?? 0)}</span>}
            />
          </Card>
        </div>
      ) : null}

      {/* Trade table */}
      <Card>
        <div className="p-3">
          {tab === "live" ? (
            <Table<LiveTrade>
              columns={liveCols}
              // O2: client-side exit_reason filter on top of fetched live trades.
              // Server returns 100 most recent; filter narrows to the lifecycle
              // event of interest (LIMIT_TTL_EXPIRED / GRACE / BAD_OPEN_PRICE / etc).
              rows={filter.exitReason
                ? liveTrades.filter((t) => t.exit_reason === filter.exitReason)
                : liveTrades}
              rowKey={(r) => r.trade_ref}
              loading={loading}
              loadingRows={5}
              emptyState={
                <EmptyState
                  title="No live trades yet"
                  description="First signal at 22:00 UTC (daily) or 08:00–10:30 UTC (London)."
                />
              }
            />
          ) : (
            <Table<BacktestTrade>
              columns={btCols}
              rows={btTrades}
              rowKey={(r, i) => `${r.date}-${r.entry}-${i}`}
              loading={loading}
              loadingRows={8}
              onRowClick={(r) => setSelected(r)}
              emptyState={
                <EmptyState
                  title="No backtest results in DB"
                  description="Run a backtest first from the Backtest page."
                />
              }
            />
          )}
        </div>

        {/* Pagination */}
        {tab === "backtest" && totalPages > 1 ? (
          <Card.Footer>
            <span className="num text-[12.5px] text-[var(--color-text-dim)] mr-auto">
              Showing {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, totalTrades)} of {totalTrades.toLocaleString()}
            </span>
            <Button size="sm" variant="ghost" onClick={() => setPage(1)} disabled={page === 1}>«</Button>
            <Button size="sm" variant="ghost" onClick={() => setPage(page - 1)} disabled={page === 1}>‹</Button>
            <span className="num text-[12px] px-2 text-[var(--color-text)] font-medium">
              {page} / {totalPages}
            </span>
            <Button size="sm" variant="ghost" onClick={() => setPage(page + 1)} disabled={page === totalPages}>›</Button>
            <Button size="sm" variant="ghost" onClick={() => setPage(totalPages)} disabled={page === totalPages}>»</Button>
          </Card.Footer>
        ) : null}
      </Card>

      {/* Trade detail sheet (backtest only — has TradeJourney chart) */}
      <Sheet
        open={!!selectedBacktest}
        onClose={() => setSelected(null)}
        side="right"
        width={720}
        title={selectedBacktest ? `${selectedBacktest.direction} · ${formatBacktestDate(selectedBacktest.date)}` : ""}
      >
        {selectedBacktest ? (
          <div className="p-3">
            <TradeJourney
              date={selectedBacktest.date}
              strategy={selectedBacktest.strategy}
              direction={selectedBacktest.direction}
              entry={selectedBacktest.entry}
              sl={selectedBacktest.sl}
              tp={selectedBacktest.tp}
              exit_price={selectedBacktest.exit_price}
              pnl={selectedBacktest.pnl_sized}
              bars_held={selectedBacktest.bars_held || 10}
              status={selectedBacktest.status}
              hold_human={selectedBacktest.hold_human}
              onClose={() => setSelected(null)}
            />
          </div>
        ) : null}
      </Sheet>
    </div>
  );
}
