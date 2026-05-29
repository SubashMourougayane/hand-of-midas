"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import TradeJourney from "@/components/TradeJourney";
import { formatINR } from "@/lib/format";
import { useInstrument } from "@/lib/instrument";

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

export default function TradesPage() {
  const { apiBase, instrument } = useInstrument();
  const API_BASE = apiBase;
  const prefix = instrument === "oil" ? "oil" : instrument === "micro" ? "micro" : "gold";
  const [tab, setTab] = useState<"live" | "backtest">("backtest");
  const [liveTrades, setLiveTrades] = useState<LiveTrade[]>([]);
  const [btTrades, setBtTrades] = useState<BacktestTrade[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState({ strategy: "", side: "", result: "", year: "" });
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalTrades, setTotalTrades] = useState(0);
  const perPage = 50;
  const [selectedTrade, setSelectedTrade] = useState<BacktestTrade | null>(null);

  const fetchTrades = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter.strategy) params.set("strategy", filter.strategy === "alpha_sweep" ? "micro_alpha_sweep" : filter.strategy);
      if (filter.side) params.set("side", filter.side);
      if (filter.result) params.set("result", filter.result.toUpperCase());

      if (tab === "live") {
        params.set("limit", "200");
        const res = await fetch(`${API_BASE}/api/${prefix}/trades?${params}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        setLiveTrades(data.trades || data || []);
        setStats(data.stats || {});
      } else {
        if (filter.year) params.set("year", filter.year);
        params.set("page", String(page));
        params.set("per_page", String(perPage));
        const res = await fetch(`${API_BASE}/api/${prefix}/trades/backtest?${params}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        setBtTrades(data.trades || []);
        setTotalPages(data.pages || 1);
        setTotalTrades(data.total || 0);
        setStats(data.stats || {});
      }
    } catch {
      setTimeout(fetchTrades, 3000);
    }
    setLoading(false);
  };

  useEffect(() => { fetchTrades(); }, [tab, filter, page, apiBase, instrument]);
  useEffect(() => { setPage(1); }, [filter, tab, instrument]);

  const stratColor = (s: string) => s.includes("alpha_sweep") ? "#4fc3f7" : s === "mean_rev" ? "#00e87b" : "#ffd54f";
  const stratLabel = (s: string) => s.includes("alpha_sweep") ? "ALPHA" : s === "mean_rev" ? "MREV" : "CROSS";

  return (
    <>
      <Sidebar />
      <main className="flex-1 p-3 sm:p-6 overflow-auto pt-14 md:pt-6">
        <h1 className="text-xl font-bold text-[var(--text)] mb-1">TRADES</h1>
        <p className="text-xs text-[var(--text-dim)] mb-4">Trade history — live execution and backtested results</p>

        {/* Tabs */}
        <div className="flex gap-1 mb-4">
          <button onClick={() => setTab("live")}
            className={`text-xs px-4 py-1.5 border ${tab === "live" ? "border-[var(--green)] text-[var(--green)] bg-[var(--green-dim)]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
            LIVE
          </button>
          <button onClick={() => setTab("backtest")}
            className={`text-xs px-4 py-1.5 border ${tab === "backtest" ? "border-[var(--blue)] text-[var(--blue)] bg-[#4da6ff10]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
            BACKTEST
          </button>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-4 flex-wrap">
          <select value={filter.strategy} onChange={(e) => setFilter({ ...filter, strategy: e.target.value })}
            className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5">
            <option value="">All Strategies</option>
            <option value="alpha_sweep">Alpha-Sweep</option>
            <option value="micro_alpha_sweep">Micro Alpha-Sweep</option>
            <option value="mean_rev">Mean-Rev</option>
            <option value="cross_market">Cross-Market</option>
          </select>
          <select value={filter.side} onChange={(e) => setFilter({ ...filter, side: e.target.value })}
            className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5">
            <option value="">All Sides</option>
            <option value="LONG">LONG</option>
            <option value="SHORT">SHORT</option>
          </select>
          <select value={filter.result} onChange={(e) => setFilter({ ...filter, result: e.target.value })}
            className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5">
            <option value="">All Results</option>
            <option value="WIN">Winners</option>
            <option value="LOSS">Losers</option>
          </select>
          {tab === "backtest" && (
            <select value={filter.year} onChange={(e) => setFilter({ ...filter, year: e.target.value })}
              className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5">
              <option value="">All Years</option>
              {Array.from({ length: 21 }, (_, i) => 2006 + i).map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          )}
        </div>

        {/* Stats */}
        {stats.total > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 mb-4">
            <div className="t-panel p-3">
              <div className="text-[9px] text-[var(--text-dim)] uppercase">Trades</div>
              <div className="text-lg font-bold">{stats.total}</div>
            </div>
            <div className="t-panel p-3">
              <div className="text-[9px] text-[var(--text-dim)] uppercase">Win Rate</div>
              <div className="text-lg font-bold">{((stats.win_rate || 0) * 100).toFixed(1)}%</div>
            </div>
            <div className="t-panel p-3">
              <div className="text-[9px] text-[var(--text-dim)] uppercase">Total P&L</div>
              <div className={`text-lg font-bold ${(stats.total_pnl || 0) >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                ${(stats.total_pnl || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
              <div className="text-[10px] text-[var(--text-dim)]">{formatINR(stats.total_pnl || 0)}</div>
            </div>
            <div className="t-panel p-3">
              <div className="text-[9px] text-[var(--text-dim)] uppercase">Avg Win</div>
              <div className="text-lg font-bold text-[var(--green)]">${(stats.avg_win || 0).toFixed(0)}</div>
              <div className="text-[10px] text-[var(--text-dim)]">{formatINR(stats.avg_win || 0)}</div>
            </div>
            <div className="t-panel p-3">
              <div className="text-[9px] text-[var(--text-dim)] uppercase">Avg Loss</div>
              <div className="text-lg font-bold text-[var(--red)]">${(stats.avg_loss || 0).toFixed(0)}</div>
              <div className="text-[10px] text-[var(--text-dim)]">{formatINR(stats.avg_loss || 0)}</div>
            </div>
          </div>
        )}

        {/* Trade Journey (when a backtest trade is selected) */}
        {selectedTrade && (
          <TradeJourney
            date={selectedTrade.date}
            strategy={selectedTrade.strategy}
            direction={selectedTrade.direction}
            entry={selectedTrade.entry}
            sl={selectedTrade.sl}
            tp={selectedTrade.tp}
            exit_price={selectedTrade.exit_price}
            pnl={selectedTrade.pnl_sized}
            bars_held={selectedTrade.bars_held || 10}
            status={selectedTrade.status}
            hold_human={selectedTrade.hold_human}
            onClose={() => setSelectedTrade(null)}
          />
        )}

        {/* Trade Table */}
        <div className="t-panel p-3 sm:p-4">
          {loading ? (
            <p className="text-xs text-[var(--text-dim)]">Loading...</p>
          ) : tab === "live" && liveTrades.length === 0 ? (
            <p className="text-xs text-[var(--text-dim)]">No live trades yet. First signal at 22:00 UTC (daily) or 08:00-10:30 UTC (London).</p>
          ) : tab === "backtest" && btTrades.length === 0 ? (
            <p className="text-xs text-[var(--text-dim)]">No backtest results in DB. Run a backtest first from the Backtest page.</p>
          ) : (
            <div className="overflow-x-auto max-h-[600px]">
              <table className="w-full text-[11px]">
                <thead className="sticky top-0 bg-[var(--panel)]">
                  <tr className="text-[var(--text-dim)]">
                    <th className="text-left py-1">Date</th>
                    <th className="text-left">Strategy</th>
                    <th className="text-left">Side</th>
                    <th className="text-right">Entry</th>
                    <th className="text-right">Exit</th>
                    <th className="text-right">P&L</th>
                    {tab === "backtest" && <th className="text-right">R</th>}
                    <th className="text-left">Exit</th>
                    <th className="text-left">{tab === "backtest" ? "Hold" : "Units"}</th>
                  </tr>
                </thead>
                <tbody>
                  {tab === "live" && liveTrades.map((t) => (
                    <tr key={t.trade_ref} className="border-t border-[var(--border)] hover:bg-[var(--panel-alt)]">
                      <td className="py-1 text-[var(--text-dim)]">
                        {t.exit_time ? new Date(t.exit_time).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                      <td><span style={{ color: stratColor(t.strategy) }}>{stratLabel(t.strategy)}</span></td>
                      <td className={t.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}>{t.side}</td>
                      <td className="text-right">${t.entry_price.toFixed(2)}</td>
                      <td className="text-right">{t.exit_price ? `$${t.exit_price.toFixed(2)}` : "—"}</td>
                      <td className={`text-right font-semibold ${(t.pnl_usd || t.pnl_gbp) >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                        ${(t.pnl_usd || t.pnl_gbp) >= 0 ? "+" : ""}{(t.pnl_usd || t.pnl_gbp).toFixed(0)}
                      </td>
                      <td className="text-[var(--yellow)]">{t.exit_reason}</td>
                      <td>{t.units}</td>
                    </tr>
                  ))}
                  {tab === "backtest" && btTrades.map((t, i) => (
                    <tr key={i} onClick={() => setSelectedTrade(t)}
                      className={`border-t border-[var(--border)] hover:bg-[var(--panel-alt)] cursor-pointer ${selectedTrade?.date === t.date && selectedTrade?.entry === t.entry ? "bg-[var(--panel-alt)]" : ""}`}>
                      <td className="py-1 text-[var(--text-dim)]">{t.date}</td>
                      <td><span style={{ color: stratColor(t.strategy) }}>{stratLabel(t.strategy)}</span></td>
                      <td className={t.direction === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}>{t.direction}</td>
                      <td className="text-right">${t.entry.toFixed(0)}</td>
                      <td className="text-right">${t.exit_price.toFixed(0)}</td>
                      <td className={`text-right font-semibold ${t.pnl_sized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                        ${t.pnl_sized >= 0 ? "+" : ""}{t.pnl_sized.toFixed(0)}
                        <span className="text-[9px] text-[var(--text-dim)] ml-0.5">({formatINR(t.pnl_sized)})</span>
                      </td>
                      <td className="text-right">{t.r_mult > 0 ? "+" : ""}{t.r_mult.toFixed(1)}R</td>
                      <td className="text-[var(--yellow)]">{t.status}</td>
                      <td>{t.hold_human}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {/* Pagination */}
          {tab === "backtest" && totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--border)]">
              <span className="text-[10px] text-[var(--text-dim)]">
                Showing {(page-1)*perPage + 1}–{Math.min(page*perPage, totalTrades)} of {totalTrades} trades
              </span>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(1)} disabled={page === 1}
                  className="px-2 py-1 text-xs border border-[var(--border)] text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-30">
                  «
                </button>
                <button onClick={() => setPage(page - 1)} disabled={page === 1}
                  className="px-2 py-1 text-xs border border-[var(--border)] text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-30">
                  ‹
                </button>
                <span className="px-3 py-1 text-xs font-bold text-[var(--text)] bg-[var(--bg)] border border-[var(--border)]">
                  {page} / {totalPages}
                </span>
                <button onClick={() => setPage(page + 1)} disabled={page === totalPages}
                  className="px-2 py-1 text-xs border border-[var(--border)] text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-30">
                  ›
                </button>
                <button onClick={() => setPage(totalPages)} disabled={page === totalPages}
                  className="px-2 py-1 text-xs border border-[var(--border)] text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-30">
                  »
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
