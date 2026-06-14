"use client";
import { useState, useEffect } from "react";
import PnlCalendar from "@/components/PnlCalendar";
import DatePicker from "@/components/DatePicker";
import { runBacktest, getLatestBacktest, BacktestResult, Trade } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";

const STRATEGIES = [
  { id: "alpha_sweep", label: "Alpha-Sweep", color: "#4fc3f7" },
  { id: "mean_rev", label: "Mean-Rev", color: "#00e87b" },
  { id: "cross_market", label: "Cross-Market", color: "#ffd54f" },
];

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

  // Load latest backtest from DB on mount or instrument change
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

  const [progressMsg, setProgressMsg] = useState("");

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

  return (
    <div className="p-3 sm:p-6">
        <h1 className="text-xl font-bold text-[var(--text)] mb-1">BACKTEST</h1>
        <p className="text-xs text-[var(--text-dim)] mb-5">
          V4 + V7 + V8 Portfolio | Fresh capital each year | Honest fills
        </p>

        {/* Config Panel */}
        <div className="t-panel p-3 sm:p-4 mb-4">
          <div className="flex flex-wrap gap-3 sm:gap-4 items-end">
            <DatePicker label="Start" value={startDate} onChange={setStartDate} />
            <DatePicker label="End" value={endDate} onChange={setEndDate} />
            <div>
              <label className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Capital</label>
              <input type="number" value={capital} onChange={(e) => setCapital(+e.target.value)}
                className="block mt-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5 w-[90px]" />
            </div>
            <div>
              <label className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Risk %</label>
              <input type="number" step="0.5" value={riskPct} onChange={(e) => setRiskPct(+e.target.value)}
                className="block mt-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5 w-[70px]" />
            </div>
            <div className="flex gap-2">
              {STRATEGIES.map((s) => (
                <button key={s.id} onClick={() => toggleStrategy(s.id)}
                  className={`text-[10px] px-2 py-1 border ${selectedStrategies.includes(s.id) ? "border-[var(--green)] text-[var(--green)]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
                  {s.label}
                </button>
              ))}
            </div>
            <button onClick={handleRun} disabled={loading || selectedStrategies.length === 0}
              className="t-btn-green text-xs px-4 py-1.5 font-semibold disabled:opacity-50">
              {loading ? "RUNNING..." : "RUN BACKTEST"}
            </button>
          </div>
        </div>

        {error && <div className="text-[var(--red)] text-xs mb-4">{error}</div>}

        {loading && <BacktestProgress instrument={instrument} progressMsg={progressMsg} />}

        {result && !loading && (
          <>
            {/* Stats Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
              <StatCard label="Total P&L" value={`$${result.stats.total_pnl.toLocaleString(undefined, {maximumFractionDigits:0})}`} sub={formatINR(result.stats.total_pnl)} color={result.stats.total_pnl >= 0 ? "green" : "red"} />
              <StatCard label="Win Rate" value={`${(result.stats.win_rate * 100).toFixed(1)}%`} sub={`${result.stats.wins}W / ${result.stats.losses}L`} />
              <StatCard label="Profit Factor" value={result.stats.profit_factor.toFixed(2)} />
              <StatCard label="Max DD" value={`${result.stats.max_drawdown_pct.toFixed(1)}%`} color="red" />
              <StatCard label="Trades" value={`${result.stats.total_trades}`} sub={`${(result.stats.total_trades / Math.max(result.yearly_pnl.length, 1)).toFixed(0)}/year`} />
              <StatCard label="R:R" value={`1:${result.stats.risk_reward.toFixed(2)}`} />
              <StatCard label="Avg Win" value={`$${result.stats.avg_win.toFixed(0)}`} sub={formatINR(result.stats.avg_win)} color="green" />
              <StatCard label="Avg Loss" value={`$${result.stats.avg_loss.toFixed(0)}`} sub={formatINR(result.stats.avg_loss)} color="red" />
            </div>

            {/* Strategy Breakdown */}
            <div className="t-panel p-3 sm:p-4 mb-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">Strategy Breakdown</h2>
              <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[var(--text-dim)]">
                    <th className="text-left py-1">Strategy</th>
                    <th className="text-right">Trades</th>
                    <th className="text-right">WR</th>
                    <th className="text-right">PF</th>
                    <th className="text-right">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.stats.strategies).map(([key, s]) => (
                    <tr key={key} className="border-t border-[var(--border)]">
                      <td className="py-1.5">
                        <span className={`inline-block px-1.5 py-0.5 text-[10px] font-semibold ${key .includes("alpha_sweep") ? "text-[#4fc3f7] bg-[#4fc3f7]/10" : key === "mean_rev" ? "text-[#00e87b] bg-[#00e87b]/10" : "text-[#ffd54f] bg-[#ffd54f]/10"}`}>
                          {key .includes("alpha_sweep") ? "ALPHA" : key === "mean_rev" ? "MEAN-REV" : "CROSS"}
                        </span>
                      </td>
                      <td className="text-right">{s.trades}</td>
                      <td className="text-right">{(s.wr * 100).toFixed(1)}%</td>
                      <td className="text-right">{s.pf.toFixed(2)}</td>
                      <td className={`text-right font-semibold ${s.pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                        ${s.pnl.toLocaleString(undefined, {maximumFractionDigits:0})}
                        <span className="text-[9px] text-[var(--text-dim)] ml-1">({formatINR(s.pnl)})</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            </div>

            {/* Session Breakdown */}
            {result.stats.sessions && (
              <div className="t-panel p-4 mb-4">
                <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">Session Breakdown (by entry time IST)</h2>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { key: "asian", label: "TOKYO", time: "3:30 AM – 1:30 PM", color: "#4da6ff", emoji: "🇯🇵" },
                    { key: "london", label: "LONDON", time: "1:30 PM – 6:30 PM", color: "#4fc3f7", emoji: "🇬🇧" },
                    { key: "overlap", label: "OVERLAP", time: "6:30 PM – 10:30 PM", color: "#ff8c00", emoji: "⚡" },
                    { key: "newyork", label: "NEW YORK", time: "10:30 PM – 3:30 AM", color: "#00e87b", emoji: "🇺🇸" },
                  ].map(({ key, label, time, color, emoji }) => {
                    const s = (result.stats.sessions as Record<string, { trades: number; wins: number; win_rate: number; pnl: number; pf: number; monthly: number }>)[key];
                    if (!s || s.trades === 0) return null;
                    return (
                      <div key={key} className="p-4 rounded-lg" style={{ background: "#0d1017", border: `1px solid ${color}22` }}>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-base">{emoji}</span>
                          <span className="text-xs font-bold" style={{ color }}>{label}</span>
                        </div>
                        <div className="text-[9px] mb-3" style={{ color: "#9ca3b4" }}>{time} IST</div>
                        <div className="space-y-1.5">
                          <div className="flex justify-between text-[11px]">
                            <span style={{ color: "#9ca3b4" }}>Trades</span>
                            <span className="font-bold text-[var(--text)]">{s.trades}</span>
                          </div>
                          <div className="flex justify-between text-[11px]">
                            <span style={{ color: "#9ca3b4" }}>Win Rate</span>
                            <span className="font-bold" style={{ color: s.win_rate >= 60 ? "#00e87b" : "#c8cdd5" }}>{s.win_rate}%</span>
                          </div>
                          <div className="flex justify-between text-[11px]">
                            <span style={{ color: "#9ca3b4" }}>P&L</span>
                            <span className="font-bold" style={{ color: s.pnl >= 0 ? "#00e87b" : "#ff3e3e" }}>
                              ${s.pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                            </span>
                          </div>
                          <div className="flex justify-between text-[11px]">
                            <span style={{ color: "#9ca3b4" }}>$/month</span>
                            <span style={{ color: s.monthly >= 0 ? "#00e87b" : "#ff3e3e" }}>${s.monthly}</span>
                          </div>
                          <div className="flex justify-between text-[11px]">
                            <span style={{ color: "#9ca3b4" }}>PF</span>
                            <span className="font-bold" style={{ color }}>{s.pf}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Equity Curve */}
            <div className="t-panel p-4 mb-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">Equity Curve (Cumulative P&L)</h2>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={result.equity_curve}>
                  <XAxis dataKey="date" tick={false} />
                  <YAxis tick={{ fontSize: 10, fill: "#9ca3b4" }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip contentStyle={{ background: "#181c24", border: "1px solid #252a33", fontSize: 11 }}
                    formatter={(v) => [`$${Number(v).toLocaleString()}`, "P&L"]} />
                  <Line type="monotone" dataKey="pnl" stroke="#00e87b" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* P&L Calendar */}
            <div className="mb-4">
              <PnlCalendar trades={result.trades} />
            </div>

            {/* Yearly Performance */}
            <div className="t-panel p-3 sm:p-4 mb-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">Year-by-Year</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-[var(--text-dim)] text-[9px] uppercase tracking-wider">
                      <th className="text-left py-1.5">Year</th>
                      <th className="text-center">Trades</th>
                      <th className="text-center">WR</th>
                      <th className="text-right">Start</th>
                      <th className="text-right">End</th>
                      <th className="text-right">P&L ($)</th>
                      <th className="text-right">P&L (₹)</th>
                      <th className="text-right">Return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.yearly_pnl.map((y: any) => (
                      <tr key={y.year} className="border-t border-[var(--border)]">
                        <td className="py-1.5 font-semibold">{y.year}</td>
                        <td className="text-center">{y.trades}</td>
                        <td className="text-center">{(y.wr * 100).toFixed(0)}%</td>
                        <td className="text-right text-[var(--text-dim)]">
                          ${(y.start_fund || 0).toLocaleString(undefined, {maximumFractionDigits:0})}
                        </td>
                        <td className="text-right text-[var(--text)]">
                          ${(y.end_fund || 0).toLocaleString(undefined, {maximumFractionDigits:0})}
                        </td>
                        <td className={`text-right font-semibold ${y.pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                          {y.pnl >= 0 ? "+" : ""}${Math.abs(y.pnl).toLocaleString(undefined, {maximumFractionDigits:0})}
                        </td>
                        <td className={`text-right ${y.pnl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                          {formatINR(y.pnl)}
                        </td>
                        <td className={`text-right font-semibold ${(y.return_pct || 0) >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                          {(y.return_pct || 0) > 0 ? "+" : ""}{y.return_pct || 0}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Trade Table */}
            <div className="t-panel p-3 sm:p-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">
                Trades ({result.trades.length} total)
              </h2>
              <div className="overflow-x-auto max-h-[500px]">
                <table className="w-full text-[11px]">
                  <thead className="sticky top-0 bg-[var(--panel)]">
                    <tr className="text-[var(--text-dim)]">
                      <th className="text-left py-1">#</th>
                      <th className="text-left">Date</th>
                      <th className="text-left">Strat</th>
                      <th className="text-left">Dir</th>
                      <th className="text-right">Entry</th>
                      <th className="text-right">Exit</th>
                      <th className="text-right">P&L</th>
                      <th className="text-right">R</th>
                      <th className="text-left">Hold</th>
                      <th className="text-left">Exit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.slice(0, showTrades).map((t, i) => (
                      <tr key={i} className="border-t border-[var(--border)] hover:bg-[var(--panel-alt)]">
                        <td className="py-1 text-[var(--text-dim)]">{i + 1}</td>
                        <td>{t.date}</td>
                        <td>
                          <span className={`text-[10px] px-1 ${t.strategy .includes("alpha_sweep") ? "text-[#4fc3f7]" : t.strategy === "mean_rev" ? "text-[#00e87b]" : "text-[#ffd54f]"}`}>
                            {t.strategy .includes("alpha_sweep") ? "ALPHA" : t.strategy === "mean_rev" ? "MREV" : "CROSS"}
                          </span>
                        </td>
                        <td className={t.direction === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {t.direction}
                        </td>
                        <td className="text-right">${t.entry.toFixed(0)}</td>
                        <td className="text-right">${t.exit_price.toFixed(0)}</td>
                        <td className={`text-right font-semibold ${t.pnl_sized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                          ${t.pnl_sized >= 0 ? "+" : ""}{t.pnl_sized.toFixed(0)}
                          <span className="text-[9px] text-[var(--text-dim)] ml-0.5">({formatINR(t.pnl_sized)})</span>
                        </td>
                        <td className="text-right">{t.r_mult > 0 ? "+" : ""}{t.r_mult.toFixed(1)}R</td>
                        <td>{t.hold_human}</td>
                        <td className="text-[var(--text-dim)]">{t.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.trades.length > showTrades && (
                <button onClick={() => setShowTrades((p) => p + 50)}
                  className="mt-2 text-xs text-[var(--blue)] hover:underline">
                  Show more ({result.trades.length - showTrades} remaining)
                </button>
              )}
            </div>

            <div className="text-[10px] text-[var(--text-dim)] mt-3">
              Computed in {(result.duration_ms / 1000).toFixed(1)}s
            </div>
          </>
        )}
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
    <div className="t-panel p-6 mb-4">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-4 h-4 border-2 border-[var(--green)] border-t-transparent animate-spin" style={{ borderRadius: "50%" }} />
        <span className="text-sm font-semibold text-[var(--text)]">Running backtest{dots}</span>
        <span className="text-xs text-[var(--text-dim)]">{elapsed}s elapsed</span>
      </div>
      {progressMsg ? (
        <div className="text-xs text-[var(--green)] font-mono">{progressMsg}</div>
      ) : (
        <div className="space-y-1.5">
          {steps.map((step, i) => (
            <div key={i} className={`text-xs flex items-center gap-2 ${i < currentStep ? "text-[var(--green)]" : i === currentStep ? "text-[var(--text)]" : "text-[var(--text-dim)]"}`}>
              <span>{i < currentStep ? "✓" : i === currentStep ? "▶" : "○"}</span>
              <span>{step}</span>
            </div>
          ))}
        </div>
      )}
      <div className="mt-4 h-1 bg-[var(--bg)] overflow-hidden">
        <div className="h-full bg-[var(--green)] transition-all duration-1000" style={{ width: `${Math.min((elapsed / 90) * 100, 95)}%` }} />
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  const colorClass = color === "green" ? "text-[var(--green)]" : color === "red" ? "text-[var(--red)]" : "text-[var(--text)]";
  return (
    <div className="t-panel p-3">
      <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">{label}</div>
      <div className={`text-lg font-bold mt-1 ${colorClass}`}>{value}</div>
      {sub && <div className="text-[10px] text-[var(--text-dim)] mt-0.5">{sub}</div>}
    </div>
  );
}
