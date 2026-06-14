"use client";
import { useEffect, useMemo, useState } from "react";
import PnlCalendar from "@/components/PnlCalendar";
import DatePicker from "@/components/DatePicker";
import { runBacktest, getLatestBacktest, BacktestResult } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  PageHeader,
  Card,
  Stat,
  Badge,
  Button,
  Skeleton,
  Table,
  type Column,
} from "@/components/ui";
import { cn } from "@/components/ui/cn";

const STRATEGIES = [
  { id: "alpha_sweep", label: "Alpha-Sweep", color: "var(--color-info)" },
  { id: "mean_rev", label: "Mean-Rev", color: "var(--color-win)" },
  { id: "cross_market", label: "Cross-Market", color: "var(--color-warn)" },
];

const STRATEGY_META: Record<string, { label: string; color: string }> = {
  alpha_sweep: { label: "Alpha", color: "var(--color-info)" },
  micro_alpha_sweep: { label: "Alpha", color: "var(--color-info)" },
  micro_alpha_sweep_oil: { label: "Alpha", color: "var(--color-info)" },
  mean_rev: { label: "MRev", color: "var(--color-win)" },
  cross_market: { label: "Cross", color: "var(--color-warn)" },
};

function strategyTag(strategy: string) {
  const key = Object.keys(STRATEGY_META).find((k) => strategy.includes(k)) ?? "cross_market";
  const meta = STRATEGY_META[key];
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: meta.color }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} aria-hidden />
      {meta.label}
    </span>
  );
}

function formatBacktestDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

interface Trade {
  date: string;
  strategy: string;
  direction: string;
  entry: number;
  exit_price: number;
  pnl_sized: number;
  r_mult: number;
  hold_human: string;
  status: string;
}

const SESSIONS = [
  { key: "asian", label: "Tokyo", time: "3:30 AM – 1:30 PM", flag: "🇯🇵" },
  { key: "london", label: "London", time: "1:30 PM – 6:30 PM", flag: "🇬🇧" },
  { key: "overlap", label: "Overlap", time: "6:30 PM – 10:30 PM", flag: "⚡" },
  { key: "newyork", label: "New York", time: "10:30 PM – 3:30 AM", flag: "🇺🇸" },
] as const;

export default function BacktestPage() {
  const { apiBase, instrument } = useInstrument();
  const [startDate, setStartDate] = useState("2006-01-01");
  const [endDate, setEndDate] = useState("2026-05-21");
  const [capital, setCapital] = useState(5000);
  const [riskPct, setRiskPct] = useState(3.0);
  const [selectedStrategies, setSelectedStrategies] = useState(["alpha_sweep", "mean_rev", "cross_market"]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showTrades, setShowTrades] = useState(50);
  const [progressMsg, setProgressMsg] = useState("");

  useEffect(() => {
    setResult(null);
    setShowTrades(50);
    setLoading(false);
    setProgressMsg("");
    setError("");
    let cancelled = false;
    getLatestBacktest(apiBase, instrument).then((data) => {
      if (cancelled) return;
      if (data) {
        setResult(data);
        if (data.config) {
          setStartDate(data.config.start_date);
          setEndDate(data.config.end_date);
          setCapital(data.config.capital);
          setRiskPct(data.config.risk_pct);
          if (data.config.strategies) setSelectedStrategies(data.config.strategies);
        }
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [apiBase, instrument]);

  const handleRun = async () => {
    setLoading(true);
    setError("");
    setProgressMsg("");
    try {
      const data = await runBacktest({
        strategies: selectedStrategies,
        start_date: startDate,
        end_date: endDate,
        capital,
        risk_pct: riskPct,
      }, apiBase, instrument, (msg) => setProgressMsg(msg));
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Backtest failed");
    }
    setLoading(false);
    setProgressMsg("");
  };

  const toggleStrategy = (id: string) => {
    setSelectedStrategies((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const tradeCols: Column<Trade>[] = useMemo(() => [
    {
      key: "n",
      header: "#",
      cell: (_t, i) => <span className="num text-[var(--color-text-muted)]">{i + 1}</span>,
      hideOnMobile: true,
    },
    {
      key: "date",
      header: "Date",
      cell: (t) => <span className="num text-[var(--color-text-muted)]">{formatBacktestDate(t.date)}</span>,
    },
    { key: "strategy", header: "Strategy", cell: (t) => strategyTag(t.strategy) },
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
      key: "hold",
      header: "Held",
      cell: (t) => <span className="text-[11px] text-[var(--color-text-dim)]">{t.hold_human}</span>,
      hideOnMobile: true,
    },
    {
      key: "status",
      header: "Exit",
      cell: (t) => <span className="text-[11px] uppercase text-[var(--color-warn)]">{t.status}</span>,
      hideOnMobile: true,
    },
  ], []);

  return (
    <div className="p-3 sm:p-6 max-w-[1280px] mx-auto">
      <PageHeader
        title="Backtest"
        description="V4 + V7 + V8 Portfolio · Fresh capital each year · Honest fills"
      />

      {/* Config panel */}
      <Card padded className="mb-4">
        <div className="flex flex-wrap gap-3 sm:gap-4 items-end">
          <DatePicker label="Start" value={startDate} onChange={setStartDate} />
          <DatePicker label="End" value={endDate} onChange={setEndDate} />
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Capital</label>
            <input
              type="number"
              value={capital}
              onChange={(e) => setCapital(+e.target.value)}
              className="w-[100px]"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Risk %</label>
            <input
              type="number"
              step="0.5"
              value={riskPct}
              onChange={(e) => setRiskPct(+e.target.value)}
              className="w-[80px]"
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)]">Strategies</span>
            <div className="flex gap-1.5 flex-wrap">
              {STRATEGIES.map((s) => {
                const active = selectedStrategies.includes(s.id);
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => toggleStrategy(s.id)}
                    className={cn(
                      "h-7 px-2.5 rounded-[4px] text-[11px] font-medium border transition-colors",
                      "flex items-center gap-1.5 whitespace-nowrap",
                    )}
                    style={
                      active
                        ? {
                            color: s.color,
                            borderColor: s.color,
                            backgroundColor: `color-mix(in srgb, ${s.color} 12%, transparent)`,
                          }
                        : {
                            color: "var(--color-text-muted)",
                            borderColor: "var(--color-border)",
                          }
                    }
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: s.color, opacity: active ? 1 : 0.4 }}
                      aria-hidden
                    />
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>
          <Button
            variant="primary"
            onClick={handleRun}
            loading={loading}
            disabled={loading || selectedStrategies.length === 0}
          >
            {loading ? "Running…" : "Run Backtest"}
          </Button>
        </div>
      </Card>

      {error ? (
        <Card padded className="mb-4 border-[var(--color-loss)]/40 bg-[var(--color-loss)]/5">
          <p className="text-[12px] text-[var(--color-loss)]">{error}</p>
        </Card>
      ) : null}

      {loading ? <BacktestProgress instrument={instrument} progressMsg={progressMsg} /> : null}

      {result && !loading ? (
        <>
          {/* Stats grid — 8 animated cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 mb-4 hom-stagger-children">
            <Card padded lift className="hom-stagger">
              <Stat
                label="Total P&L"
                value={result.stats.total_pnl}
                animate
                prefix={result.stats.total_pnl >= 0 ? "+$" : "−$"}
                tone={result.stats.total_pnl >= 0 ? "win" : "loss"}
                hint={<span className="num">{formatINR(Math.abs(result.stats.total_pnl))}</span>}
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="Win rate"
                value={result.stats.win_rate * 100}
                animate
                decimals={1}
                suffix="%"
                tone={result.stats.win_rate > 0.5 ? "win" : "neutral"}
                hint={<span className="num">{result.stats.wins}W / {result.stats.losses}L</span>}
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="Profit factor"
                value={result.stats.profit_factor}
                animate
                decimals={2}
                tone="brass"
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="Max DD"
                value={result.stats.max_drawdown_pct}
                animate
                decimals={1}
                suffix="%"
                tone="loss"
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="Trades"
                value={result.stats.total_trades}
                animate
                hint={<span className="num">{(result.stats.total_trades / Math.max(result.yearly_pnl.length, 1)).toFixed(0)}/year</span>}
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="R:R"
                value={`1 : ${result.stats.risk_reward.toFixed(2)}`}
                tone="brass"
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="Avg win"
                value={result.stats.avg_win}
                animate
                prefix="+$"
                tone="win"
                hint={<span className="num">{formatINR(result.stats.avg_win)}</span>}
              />
            </Card>
            <Card padded lift className="hom-stagger">
              <Stat
                label="Avg loss"
                value={Math.abs(result.stats.avg_loss)}
                animate
                prefix="−$"
                tone="loss"
                hint={<span className="num">{formatINR(result.stats.avg_loss)}</span>}
              />
            </Card>
          </div>

          {/* Strategy breakdown */}
          <Card className="mb-4">
            <Card.Header>
              <Card.Title>Strategy breakdown</Card.Title>
            </Card.Header>
            <div className="px-3 pb-3">
              <table className="w-full text-[12px]">
                <thead>
                  <tr>
                    <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Strategy</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Trades</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">WR</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">PF</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.stats.strategies).map(([key, s]) => (
                    <tr key={key} className="border-t border-[var(--color-border)]/60">
                      <td className="py-2">{strategyTag(key)}</td>
                      <td className="py-2 text-right num">{s.trades}</td>
                      <td className="py-2 text-right num">{(s.wr * 100).toFixed(1)}%</td>
                      <td className="py-2 text-right num">{s.pf.toFixed(2)}</td>
                      <td className={`py-2 text-right num font-semibold ${s.pnl >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                        {s.pnl >= 0 ? "+" : ""}${s.pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        <span className="text-[10px] text-[var(--color-text-muted)] ml-1">({formatINR(s.pnl)})</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Session breakdown */}
          {result.stats.sessions ? (
            <Card className="mb-4">
              <Card.Header>
                <Card.Title>Session breakdown</Card.Title>
                <span className="text-[11px] text-[var(--color-text-muted)]">by entry time IST</span>
              </Card.Header>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 hom-stagger-children">
                {SESSIONS.map(({ key, label, time, flag }) => {
                  const s = (result.stats.sessions as Record<string, { trades: number; wins: number; win_rate: number; pnl: number; pf: number; monthly: number }>)[key];
                  if (!s || s.trades === 0) return null;
                  return (
                    <Card key={key} surface={2} padded lift className="hom-stagger">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-base">{flag}</span>
                        <span className="text-[11px] font-semibold uppercase tracking-[0.6px] text-[var(--color-brass-hi)]">{label}</span>
                      </div>
                      <div className="text-[10px] text-[var(--color-text-muted)] mb-3 num">{time}</div>
                      <div className="flex flex-col gap-1.5 text-[12px]">
                        <Row label="Trades" value={<span className="num">{s.trades}</span>} />
                        <Row
                          label="Win rate"
                          value={
                            <span className={`num ${s.win_rate >= 60 ? "text-[var(--color-win)]" : "text-[var(--color-text)]"}`}>
                              {s.win_rate}%
                            </span>
                          }
                        />
                        <Row
                          label="P&L"
                          value={
                            <span className={`num font-semibold ${s.pnl >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                              ${s.pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                            </span>
                          }
                        />
                        <Row
                          label="$/month"
                          value={
                            <span className={`num ${s.monthly >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                              ${s.monthly}
                            </span>
                          }
                        />
                        <Row label="PF" value={<span className="num text-[var(--color-brass-hi)]">{s.pf}</span>} />
                      </div>
                    </Card>
                  );
                })}
              </div>
            </Card>
          ) : null}

          {/* Equity curve */}
          <Card className="mb-4">
            <Card.Header>
              <Card.Title>Equity curve</Card.Title>
              <span className="text-[11px] text-[var(--color-text-muted)] num">cumulative P&L</span>
            </Card.Header>
            <div className="p-3">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={result.equity_curve}>
                  <XAxis dataKey="date" tick={false} stroke="var(--color-border-hi)" />
                  <YAxis
                    tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                    stroke="var(--color-border-hi)"
                  />
                  <Tooltip
                    contentStyle={{
                      background: "var(--color-surface-2)",
                      border: "1px solid var(--color-border-hi)",
                      fontSize: 11,
                      borderRadius: 5,
                      color: "var(--color-text)",
                    }}
                    formatter={(v) => [`$${Number(v).toLocaleString()}`, "P&L"]}
                  />
                  <Line type="monotone" dataKey="pnl" stroke="var(--color-brass)" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* P&L Calendar */}
          <div className="mb-4">
            <PnlCalendar trades={result.trades} />
          </div>

          {/* Year-by-year */}
          <Card className="mb-4">
            <Card.Header>
              <Card.Title>Year-by-year</Card.Title>
            </Card.Header>
            <div className="px-3 pb-3 overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr>
                    <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Year</th>
                    <th className="text-center py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Trades</th>
                    <th className="text-center py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">WR</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Start</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">End</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">P&L ($)</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium hidden md:table-cell">P&L (₹)</th>
                    <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Return</th>
                  </tr>
                </thead>
                <tbody>
                  {result.yearly_pnl.map((y) => (
                    <tr key={y.year} className="border-t border-[var(--color-border)]/60">
                      <td className="py-1.5 num font-semibold text-[var(--color-text)]">{y.year}</td>
                      <td className="py-1.5 text-center num">{y.trades}</td>
                      <td className="py-1.5 text-center num">{(y.wr * 100).toFixed(0)}%</td>
                      <td className="py-1.5 text-right num text-[var(--color-text-muted)]">${(y.start_fund || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                      <td className="py-1.5 text-right num text-[var(--color-text)]">${(y.end_fund || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                      <td className={`py-1.5 text-right num font-semibold ${y.pnl >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                        {y.pnl >= 0 ? "+" : ""}${Math.abs(y.pnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </td>
                      <td className={`py-1.5 text-right num hidden md:table-cell ${y.pnl >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                        {formatINR(y.pnl)}
                      </td>
                      <td className={`py-1.5 text-right num font-semibold ${(y.return_pct || 0) >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                        {(y.return_pct || 0) > 0 ? "+" : ""}{y.return_pct || 0}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Trade table */}
          <Card>
            <Card.Header>
              <Card.Title>Trades</Card.Title>
              <span className="text-[11px] text-[var(--color-text-muted)] num">
                {showTrades.toLocaleString()} of {result.trades.length.toLocaleString()}
              </span>
            </Card.Header>
            <div className="p-3">
              <Table<Trade>
                columns={tradeCols}
                rows={result.trades.slice(0, showTrades) as Trade[]}
                rowKey={(_, i) => i}
                stickyHeader
              />
            </div>
            {result.trades.length > showTrades ? (
              <Card.Footer>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setShowTrades((p) => p + 50)}
                >
                  Show 50 more · {(result.trades.length - showTrades).toLocaleString()} remaining
                </Button>
              </Card.Footer>
            ) : null}
          </Card>

          <p className="text-[10px] text-[var(--color-text-muted)] mt-3 num">
            Computed in {(result.duration_ms / 1000).toFixed(1)}s
          </p>
        </>
      ) : !loading ? (
        <Card padded>
          <div className="flex flex-col gap-2">
            <Skeleton width="40%" height={14} />
            <Skeleton width="60%" height={12} />
            <Skeleton width="80%" height={120} rounded="md" />
          </div>
          <p className="text-[12px] text-[var(--color-text-muted)] mt-4">
            No backtest in DB yet. Configure above and Run Backtest.
          </p>
        </Card>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[10px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">{label}</span>
      <span>{value}</span>
    </div>
  );
}

function BacktestProgress({ instrument, progressMsg }: { instrument: string; progressMsg?: string }) {
  const [elapsed, setElapsed] = useState(0);
  const [dots, setDots] = useState("");

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(e => e + 1);
      setDots(d => d.length >= 3 ? "" : d + ".");
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const steps = instrument === "oil"
    ? ["Loading 20 years of oil data", "Generating Alpha-Sweep signals (M3)", "Executing trades with DD protection", "Computing statistics"]
    : instrument === "micro"
    ? ["Loading 20 years of data", "Generating Micro Alpha-Sweep signals (rolling 4hr)", "Executing trades with DD protection", "Computing statistics"]
    : ["Loading 20 years of data", "Generating Cross-Market signals", "Generating Mean-Rev signals", "Generating Alpha-Sweep signals (M3)", "Executing trades with DD protection", "Computing statistics"];

  const currentStep = Math.min(Math.floor(elapsed / 15), steps.length - 1);

  return (
    <Card padded className="mb-4">
      <div className="flex items-center gap-3 mb-4">
        <div
          className="w-4 h-4 rounded-full border-2 border-[var(--color-brass)] border-t-transparent animate-spin"
          aria-hidden
        />
        <span className="text-[14px] font-semibold text-[var(--color-text)]">
          Running backtest{dots}
        </span>
        <span className="num text-[11px] text-[var(--color-text-muted)]">{elapsed}s</span>
      </div>
      {progressMsg ? (
        <div className="num text-[12px] text-[var(--color-brass-hi)]">{progressMsg}</div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {steps.map((step, i) => (
            <div
              key={i}
              className={cn(
                "text-[12px] flex items-center gap-2",
                i < currentStep
                  ? "text-[var(--color-win)]"
                  : i === currentStep
                    ? "text-[var(--color-text)]"
                    : "text-[var(--color-text-muted)]",
              )}
            >
              <span aria-hidden>{i < currentStep ? "✓" : i === currentStep ? "▶" : "○"}</span>
              <span>{step}</span>
            </div>
          ))}
        </div>
      )}
      <div className="mt-4 h-1 bg-[var(--color-surface-2)] overflow-hidden rounded-full">
        <div
          className="h-full bg-[var(--color-brass)] transition-all duration-1000"
          style={{ width: `${Math.min((elapsed / 90) * 100, 95)}%` }}
        />
      </div>
    </Card>
  );
}
