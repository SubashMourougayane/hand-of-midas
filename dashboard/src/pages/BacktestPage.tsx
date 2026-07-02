import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Calendar } from "lucide-react";
import {
  api,
  Run,
  Trade,
  SignalRow as SignalRowT,
  FunnelBucket,
} from "../lib/api";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { DataGrid } from "../components/DataGrid";
import { KPI } from "../components/KPI";
import { Funnel } from "../components/Funnel";
import { EquityCurve } from "../components/EquityCurve";
import { PnlCalendar } from "../components/PnlCalendar";
import { FilterBar } from "../components/FilterBar";
import { applyFilter, EMPTY_FILTER, FilterState, hasAnyFilter } from "../lib/filters";
import {
  barsToDuration,
  colorForR,
  contractSizeFor,
  fmtMoney,
  fmtPriceFor,
  fmtR,
  fmtRiskFor,
  fmtTs,
  tradePnlReal,
} from "../lib/format";

// Note: BT runs use qty=1.0 (pure strategy, no sizing). R-multiples are the
// universal unit. Dollar PnL requires applying a sizing model (Model B 1.5% etc)
// which is a live-only concern. Keep this page R-only — no fake $ conversion.

function RunPicker({
  runs,
  selectedRunId,
  onSelectRun,
  analytics,
  loading,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
  analytics: { first?: string; last?: string; years: number };
  loading: boolean;
}) {
  // Group runs by strategy_id, sort each group by start_ts desc.
  const grouped = useMemo(() => {
    const map: Record<string, Run[]> = {};
    runs.forEach((r) => {
      const k = r.strategy_id;
      if (!map[k]) map[k] = [];
      map[k].push(r);
    });
    Object.values(map).forEach((arr) =>
      arr.sort(
        (a, b) => new Date(b.start_ts).getTime() - new Date(a.start_ts).getTime()
      )
    );
    return Object.entries(map).sort((a, b) => a[0].localeCompare(b[0]));
  }, [runs]);

  return (
    <div className="flex items-center gap-3 shrink-0 flex-wrap">
      <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
        backtest run
      </span>
      <select
        className="
          flex-1 min-w-[360px] bg-bg-elevated border border-line-base rounded-ds-sm
          text-ds-sm text-ink-primary px-3 py-1.5
          focus:outline-none focus:border-brass
        "
        value={selectedRunId ?? ""}
        onChange={(e) => onSelectRun(e.target.value)}
      >
        {grouped.map(([strategy, gRuns]) => (
          <optgroup key={strategy} label={`${strategy}  (${gRuns.length})`}>
            {gRuns.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.symbol} · {fmtTs(r.start_ts).slice(0, 16)} · {r.run_ref.slice(-8)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {analytics.first && analytics.last && (
        <div className="flex items-center gap-2 text-ds-xs">
          <Calendar size={13} className="text-ink-muted" />
          <span className="font-mono text-ink-primary">
            {analytics.first.slice(0, 10)}
          </span>
          <span className="text-ink-muted">→</span>
          <span className="font-mono text-ink-primary">
            {analytics.last.slice(0, 10)}
          </span>
          <span className="text-ink-muted">
            ({analytics.years.toFixed(1)} years)
          </span>
        </div>
      )}
      {loading && (
        <span className="text-ds-xs text-ink-muted animate-ds-pulse">
          loading…
        </span>
      )}
    </div>
  );
}


export function BacktestPage({
  runs,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
}) {
  // Auto-pick latest *finished* BT run (end_ts set). In-progress seeders have
  // no trades persisted until the bulk flush, so they'd render as empty.
  const latestRun = useMemo(() => {
    if (runs.length === 0) return null;
    const sorted = [...runs].sort(
      (a, b) => new Date(b.start_ts).getTime() - new Date(a.start_ts).getTime()
    );
    const finished = sorted.find((r) => r.end_ts != null);
    return finished ?? sorted[0];
  }, [runs]);
  const selectedRunId = latestRun?.run_id ?? null;
  const symbol = latestRun?.symbol;
  const contract = contractSizeFor(symbol);

  const [detail, setDetail] = useState<any>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<SignalRowT[]>([]);
  const [funnel, setFunnel] = useState<FunnelBucket[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER);
  const PAGE_SIZE = 50;
  const nav = useNavigate();

  // Filter-aware subset is the source of truth for KPIs / equity / calendar / year.
  const tf = latestRun?.timeframe ?? "M5";
  const filtered = useMemo(
    () => applyFilter(trades, filter, tf, symbol),
    [trades, filter, tf, symbol]
  );
  const isFiltered = hasAnyFilter(filter);

  useEffect(() => {
    if (!selectedRunId) return;
    setLoading(true);
    setPage(1);
    Promise.all([
      api.runDetail(selectedRunId),
      api.runTrades(selectedRunId, undefined, 1, 50000),
      api.signalsRecent({ run_id: selectedRunId, limit: 300 }),
      api.funnel(selectedRunId).catch(() => ({ buckets: [] as FunnelBucket[] })),
    ])
      .then(([d, t, s, f]) => {
        setDetail(d);
        setTrades(t.items);
        setSignals(s);
        setFunnel(f.buckets);
      })
      .finally(() => setLoading(false));
  }, [selectedRunId]);

  // Reset paginator when filter changes so user lands on page 1 of new set.
  useEffect(() => {
    setPage(1);
  }, [filter]);

  // Compute analytics from FILTERED set (single source of truth, reflects chips).
  const analytics = useMemo(() => {
    const closed = filtered.filter((t) => t.net_r != null && t.entry_timestamp);
    closed.sort(
      (a, b) =>
        new Date(a.entry_timestamp).getTime() -
        new Date(b.entry_timestamp).getTime()
    );
    const n = closed.length;
    const wins = closed.filter((t) => (t.net_r ?? 0) > 0);
    const losses = closed.filter((t) => (t.net_r ?? 0) < 0);
    const netSum = closed.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const winSum = wins.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const lossSum = Math.abs(losses.reduce((s, t) => s + (t.net_r ?? 0), 0));
    const pf = lossSum > 0 ? winSum / lossSum : winSum > 0 ? Infinity : 0;
    const wr = n > 0 ? (wins.length / n) * 100 : 0;
    const avg = n > 0 ? netSum / n : 0;

    // $ PnL @ 1.0 lot — real, derived from gross_r × risk_units × contract_size.
    const pnlPerTrade = closed.map((t) => tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features) ?? 0);
    const pnlUsd = pnlPerTrade.reduce((s, p) => s + p, 0);
    const avgPnl = n > 0 ? pnlUsd / n : 0;

    // Drawdown walk (both R and $)
    let peakR = 0,
      cumR = 0,
      maxDDR = 0,
      peakD = 0,
      cumD = 0,
      maxDDD = 0;
    closed.forEach((t, i) => {
      cumR += t.net_r ?? 0;
      peakR = Math.max(peakR, cumR);
      const ddr = cumR - peakR;
      if (ddr < maxDDR) maxDDR = ddr;
      cumD += pnlPerTrade[i];
      peakD = Math.max(peakD, cumD);
      const ddd = cumD - peakD;
      if (ddd < maxDDD) maxDDD = ddd;
    });
    const mar = Math.abs(maxDDR) > 0 ? netSum / Math.abs(maxDDR) : Infinity;
    const marUsd = Math.abs(maxDDD) > 0 ? pnlUsd / Math.abs(maxDDD) : Infinity;

    const first = closed[0]?.entry_timestamp;
    const last = closed[closed.length - 1]?.entry_timestamp;
    const years =
      first && last
        ? (new Date(last).getTime() - new Date(first).getTime()) /
          (365.25 * 24 * 3600 * 1000)
        : 0;
    const trPerYr = years > 0 ? n / years : 0;
    const rPerYr = years > 0 ? netSum / years : 0;
    const usdPerYr = years > 0 ? pnlUsd / years : 0;

    // Year-by-year breakdown (R + $)
    const byYearR: Record<string, number> = {};
    const byYearUsd: Record<string, number> = {};
    // Month-by-month (for POS MONTHS KPI)
    const byMonthUsd: Record<string, number> = {};
    closed.forEach((t, i) => {
      const y = t.entry_timestamp.slice(0, 4);
      const m = t.entry_timestamp.slice(0, 7);
      byYearR[y] = (byYearR[y] || 0) + (t.net_r ?? 0);
      byYearUsd[y] = (byYearUsd[y] || 0) + pnlPerTrade[i];
      byMonthUsd[m] = (byMonthUsd[m] || 0) + pnlPerTrade[i];
    });
    const yearCount = Object.keys(byYearR).length;
    const posYears = Object.values(byYearR).filter((v) => v > 0).length;
    const monthCount = Object.keys(byMonthUsd).length;
    const posMonths = Object.values(byMonthUsd).filter((v) => v > 0).length;

    return {
      n,
      wins: wins.length,
      losses: losses.length,
      netSum,
      pnlUsd,
      avgPnl,
      pf,
      wr,
      avg,
      maxDD: maxDDR,
      maxDDD,
      mar,
      marUsd,
      first,
      last,
      years,
      trPerYr,
      rPerYr,
      usdPerYr,
      byYearR,
      byYearUsd,
      byMonthUsd,
      pnlPerTrade,
      posYears,
      yearCount,
      posMonths,
      monthCount,
    };
  }, [filtered, symbol]);

  const totalSignals = funnel.reduce((s, b) => s + b.count, 0);
  const passed = funnel.find((b) => b.status === "GATE_SIGNAL_PASSED")?.count ?? 0;
  const pagedTrades = useMemo(() => {
    const sorted = [...filtered].sort(
      (a, b) =>
        new Date(b.entry_timestamp).getTime() -
        new Date(a.entry_timestamp).getTime()
    );
    return sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  }, [filtered, page]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  if (runs.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center p-10">
        <div className="font-display text-ds-2xl text-ink-secondary mb-2">
          No backtest runs found
        </div>
        <div className="text-ink-muted text-ds-sm max-w-md">
          Run a backtest from the CLI to populate this view:
          <code className="block mt-3 font-mono text-ds-xs text-ink-secondary bg-bg-elevated p-2 rounded-ds">
            python3 -m bt_engine.runner.cli bt --strategy fib_v2_intraday_a
          </code>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <div className="flex flex-col gap-3 p-3 min-h-0 max-w-[1800px] mx-auto">
        {/* Header strip — latest run + period + symbol context. */}
        <div className="flex items-center gap-3 shrink-0 flex-wrap py-1">
          <div className="flex items-center gap-2">
            <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
              run
            </span>
            <span className="font-mono text-ds-md font-semibold text-ink-primary">
              {latestRun?.strategy_id}
            </span>
            <span className="text-ink-muted">·</span>
            <span className="font-mono text-ds-sm text-brass-hi">
              {symbol}
            </span>
            <span className="text-ink-muted">·</span>
            <span className="font-mono text-ds-xs text-ink-muted">
              {latestRun?.timeframe}
            </span>
          </div>
          {analytics.first && analytics.last && (
            <div className="flex items-center gap-2 text-ds-xs pl-3 border-l border-line-subtle">
              <Calendar size={13} className="text-ink-muted" />
              <span className="font-mono text-ink-primary">
                {analytics.first.slice(0, 10)}
              </span>
              <span className="text-ink-muted">→</span>
              <span className="font-mono text-ink-primary">
                {analytics.last.slice(0, 10)}
              </span>
              <span className="text-ink-muted">
                ({analytics.years.toFixed(1)} yrs)
              </span>
            </div>
          )}
          <div className="flex items-center gap-2 text-ds-xs pl-3 border-l border-line-subtle">
            <span className="text-ink-muted">contract</span>
            <span className="font-mono text-ink-primary">
              {contract.toLocaleString()}{" "}
              {symbol?.startsWith("XAU") ? "oz" : symbol?.startsWith("BRENT") ? "bbl" : "units"} / lot
            </span>
          </div>
          {loading && (
            <span className="text-ds-xs text-ink-muted animate-ds-pulse ml-auto">
              loading {trades.length.toLocaleString()} trades…
            </span>
          )}
        </div>

        {/* KPI strip — $ primary, R secondary. 1.0 lot sizing baseline. */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 shrink-0">
          <KPI
            label="Net P&L"
            value={
              <span className={colorForR(analytics.pnlUsd)}>
                {fmtMoney(analytics.pnlUsd, 0)}
              </span>
            }
            sub={`${fmtMoney(analytics.usdPerYr, 0)} / yr · ${fmtR(analytics.netSum)}R`}
            deltaTone={analytics.pnlUsd >= 0 ? "bull" : "bear"}
            loading={loading}
          />
          <KPI
            label="Trades"
            value={analytics.n.toLocaleString()}
            sub={`${analytics.trPerYr.toFixed(0)} / yr`}
            loading={loading}
          />
          <KPI
            label="Win Rate"
            value={`${analytics.wr.toFixed(1)}%`}
            sub={`${analytics.wins} W / ${analytics.losses} L`}
            loading={loading}
          />
          <KPI
            label="Profit Factor"
            value={Number.isFinite(analytics.pf) ? analytics.pf.toFixed(2) : "∞"}
            sub={`avg ${fmtMoney(analytics.avgPnl, 0)}`}
            deltaTone={analytics.pf >= 1.3 ? "bull" : analytics.pf >= 1 ? "neutral" : "bear"}
            loading={loading}
          />
          <KPI
            label="Max DD"
            value={
              <span className="text-bear">{fmtMoney(analytics.maxDDD, 0)}</span>
            }
            sub={`${fmtR(analytics.maxDD)}R · MAR ${Number.isFinite(analytics.marUsd) ? analytics.marUsd.toFixed(2) : "∞"}`}
            loading={loading}
          />
          <KPI
            label="Pos Years"
            value={`${analytics.posYears}/${analytics.yearCount}`}
            sub={
              analytics.yearCount > 0
                ? `${((analytics.posYears / analytics.yearCount) * 100).toFixed(0)}%`
                : "—"
            }
            deltaTone={
              analytics.yearCount > 0 && analytics.posYears / analytics.yearCount >= 0.7
                ? "bull"
                : "bear"
            }
            loading={loading}
          />
          <KPI
            label="Pos Months"
            value={`${analytics.posMonths}/${analytics.monthCount}`}
            sub={
              analytics.monthCount > 0
                ? `${((analytics.posMonths / analytics.monthCount) * 100).toFixed(0)}%`
                : "—"
            }
            deltaTone={
              analytics.monthCount > 0 && analytics.posMonths / analytics.monthCount >= 0.6
                ? "bull"
                : "bear"
            }
            loading={loading}
          />
          <KPI
            label="Avg / Trade"
            value={
              <span className={colorForR(analytics.avgPnl)}>
                {fmtMoney(analytics.avgPnl, 1)}
              </span>
            }
            sub={`${fmtR(analytics.avg, 3)}R`}
            deltaTone={analytics.avgPnl >= 0 ? "bull" : "bear"}
            loading={loading}
          />
        </div>

        {/* Equity curve full-width — reflects filter */}
        <Pane
          title="Equity Curve"
          subtitle={isFiltered ? `filtered · ${filtered.length.toLocaleString()} trades` : "cumulative $ P&L (1.0 lot)"}
        >
          <div className="h-72">
            <EquityCurve trades={filtered} symbol={symbol} />
          </div>
        </Pane>

        {/* Calendar + Funnel side-by-side */}
        <div className="grid grid-cols-12 gap-3">
          <Pane className="col-span-12 lg:col-span-8" title="" padded={false}>
            <PnlCalendar trades={filtered} symbol={symbol} />
          </Pane>
          <Pane
            title="Gate Funnel"
            subtitle={totalSignals.toLocaleString() + " events"}
            className="col-span-12 lg:col-span-4 min-h-[400px]"
          >
            {totalSignals === 0 ? (
              <div className="px-3 py-6 text-center text-ink-muted text-ds-sm">
                <div>No gate events for this run.</div>
                <div className="text-ds-xs mt-2 text-ink-muted">
                  Pre-instrumentation BT. Re-run with current code to populate.
                </div>
              </div>
            ) : (
              <Funnel buckets={funnel} total={totalSignals} />
            )}
          </Pane>
        </div>

        {/* Year-by-year — primary $ PnL, secondary R underneath */}
        <Pane title="Year-by-Year" subtitle={`${analytics.yearCount} years`}>
          <div className="px-3 py-2 grid grid-cols-3 sm:grid-cols-6 lg:grid-cols-11 gap-2">
            {Object.entries(analytics.byYearUsd)
              .sort()
              .map(([y, usd]) => {
                const r = analytics.byYearR[y] ?? 0;
                return (
                  <div
                    key={y}
                    className={`bg-bg-elevated border rounded-ds-sm p-2 ${
                      usd > 0 ? "border-bull/30" : "border-bear/30"
                    }`}
                  >
                    <div className="text-ds-xs text-ink-muted">{y}</div>
                    <div
                      className={`font-mono text-ds-sm font-semibold ${
                        usd >= 0 ? "text-bull" : "text-bear"
                      }`}
                    >
                      {fmtMoney(usd, 0)}
                    </div>
                    <div className="text-ds-xs text-ink-muted font-mono">
                      {fmtR(r)}R
                    </div>
                  </div>
                );
              })}
          </div>
        </Pane>

        {/* Trades — paginated, filter-aware. Filter bar lives inside the pane
            but state is shared with KPIs/equity/calendar above — single source. */}
        <Pane
          title="Trades"
          subtitle={
            isFiltered
              ? `${filtered.length.toLocaleString()} of ${trades.length.toLocaleString()} · page ${page} of ${totalPages}`
              : `${filtered.length.toLocaleString()} · page ${page} of ${totalPages}`
          }
          toolbar={
            <div className="flex items-center gap-3 text-ds-xs flex-wrap w-full">
              <div className="flex-1 min-w-0">
                <FilterBar
                  trades={trades}
                  filtered={filtered}
                  filter={filter}
                  setFilter={setFilter}
                  symbol={symbol}
                  tf={tf}
                />
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-auto">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-2 py-1 rounded-ds-sm border border-line-base text-ink-secondary hover:text-ink-primary disabled:opacity-30"
              >
                ← prev
              </button>
              <span className="font-mono text-ink-muted">
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length.toLocaleString()}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-2 py-1 rounded-ds-sm border border-line-base text-ink-secondary hover:text-ink-primary disabled:opacity-30"
              >
                next →
              </button>
              </div>
            </div>
          }
        >
          <DataGrid<Trade>
            rows={pagedTrades}
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
                header: "Side",
                cell: (t) => (
                  <Pill tone={t.side > 0 ? "bull" : "bear"}>
                    {t.direction.toUpperCase()}
                  </Pill>
                ),
              },
              {
                header: "Leg",
                cell: (t) => (
                  <span className="font-mono text-ds-sm text-ink-secondary">
                    {t.leg ?? "—"}
                  </span>
                ),
              },
              {
                header: "Entry",
                cell: (t) => (
                  <span className="font-mono text-ds-xs text-ink-secondary">
                    {fmtTs(t.entry_timestamp)}
                  </span>
                ),
              },
              {
                header: "Entry",
                cell: (t) => (
                  <span className="font-mono">
                    {fmtPriceFor(symbol, t.entry_price)}
                  </span>
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
                header: "Risk",
                cell: (t) => (
                  <span className="font-mono text-ds-xs text-ink-secondary">
                    {fmtRiskFor(symbol, t.risk_units)}
                  </span>
                ),
                align: "right",
              },
              {
                header: "Held",
                cell: (t) => (
                  <span className="font-mono text-ink-secondary">
                    {barsToDuration(t.bars_held, tf)}
                  </span>
                ),
                align: "right",
              },
              {
                header: "Net R",
                cell: (t) => (
                  <span
                    className={`font-mono text-ds-xs ${colorForR(t.net_r)}`}
                  >
                    {fmtR(t.net_r)}
                  </span>
                ),
                align: "right",
              },
              {
                header: "$ PnL",
                cell: (t) => {
                  const pnl = tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features);
                  return (
                    <span
                      className={`font-mono font-semibold ${colorForR(pnl)}`}
                    >
                      {fmtMoney(pnl, 0)}
                    </span>
                  );
                },
                align: "right",
              },
            ]}
          />
        </Pane>
      </div>
    </div>
  );
}
