"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { useInstrument } from "@/lib/instrument";

interface JournalEvent {
  id: number; timestamp: string; trade_ref: string;
  strategy: string; event_type: string; price: number; context: Record<string, unknown>;
}

interface BacktestTrade {
  date: string; year: number; strategy: string; direction: string;
  entry: number; sl: number; tp: number; exit_price: number;
  pnl_sized: number; status: string; hold_human: string; r_mult: number;
}

export default function JournalPage() {
  const { apiBase, instrument } = useInstrument();
  const API_BASE = apiBase;
  const prefix = instrument === "oil" ? "oil" : instrument === "micro" ? "micro" : "gold";
  const [tab, setTab] = useState<"live" | "backtest">("live");
  const [events, setEvents] = useState<JournalEvent[]>([]);
  const [btTrades, setBtTrades] = useState<BacktestTrade[]>([]);
  const [filter, setFilter] = useState({ strategy: "", event_type: "" });
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      if (tab === "live") {
        const params = new URLSearchParams();
        if (filter.strategy) params.set("strategy", filter.strategy);
        if (filter.event_type) params.set("event_type", filter.event_type);
        params.set("limit", "100");
        const res = await fetch(`${API_BASE}/api/${prefix}/journal/events?${params}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        setEvents(data.events || []);
      } else {
        const params = new URLSearchParams();
        if (filter.strategy) params.set("strategy", filter.strategy);
        params.set("limit", "500");
        const res = await fetch(`${API_BASE}/api/${prefix}/trades/backtest?${params}`);
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        setBtTrades(data.trades || []);
      }
    } catch {
      setTimeout(fetchData, 3000);
    }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, [tab, filter, apiBase, instrument]);

  const eventColor = (type: string) => {
    if (type.includes("ENTRY") || type === "SIGNAL") return "#00e87b";
    if (type.includes("EXIT") || type.includes("SL") || type.includes("TP")) return "#ff3e3e";
    if (type.includes("SKIP") || type.includes("PAUSE")) return "#e8c300";
    if (type.includes("ERROR")) return "#ff3e3e";
    if (type.includes("BREAK_EVEN")) return "#4da6ff";
    return "#9ca3b4";
  };

  const stratColor = (s: string) => s .includes("alpha_sweep") ? "#4fc3f7" : s === "mean_rev" ? "#00e87b" : s === "cross_market" ? "#ffd54f" : "#9ca3b4";
  const stratLabel = (s: string) => s .includes("alpha_sweep") ? "ALPHA" : s === "mean_rev" ? "MREV" : s === "cross_market" ? "CROSS" : "SYS";

  return (
    <>
      <Sidebar />
      <main className="flex-1 p-3 sm:p-6 overflow-auto pt-14 md:pt-6">
        <h1 className="text-xl font-bold text-[var(--text)] mb-1">JOURNAL</h1>
        <p className="text-xs text-[var(--text-dim)] mb-4">Event log and trade narratives</p>

        {/* Tabs */}
        <div className="flex gap-1 mb-4">
          <button onClick={() => setTab("live")}
            className={`text-xs px-4 py-1.5 border ${tab === "live" ? "border-[var(--green)] text-[var(--green)] bg-[var(--green-dim)]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
            LIVE EVENTS
          </button>
          <button onClick={() => setTab("backtest")}
            className={`text-xs px-4 py-1.5 border ${tab === "backtest" ? "border-[var(--blue)] text-[var(--blue)] bg-[#4da6ff10]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
            BACKTEST JOURNAL
          </button>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-4 flex-wrap">
          <select value={filter.strategy} onChange={(e) => setFilter({ ...filter, strategy: e.target.value })}
            className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5">
            <option value="">All Strategies</option>
            <option value="alpha_sweep">Alpha-Sweep</option>
            <option value="mean_rev">Mean-Rev</option>
            <option value="cross_market">Cross-Market</option>
            {tab === "live" && <option value="system">System</option>}
          </select>
          {tab === "live" && (
            <select value={filter.event_type} onChange={(e) => setFilter({ ...filter, event_type: e.target.value })}
              className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2 py-1.5">
              <option value="">All Events</option>
              <option value="ENTRY_FILLED">Entry</option>
              <option value="EXIT_FILLED">Exit</option>
              <option value="SIGNAL_SKIPPED">Skipped</option>
              <option value="BREAK_EVEN">Break-Even</option>
              <option value="ERROR">Errors</option>
              <option value="DAILY_SCAN_START">Daily Scan</option>
            </select>
          )}
          <button onClick={fetchData} className="text-xs px-3 py-1.5 border border-[var(--border)] text-[var(--text-dim)] hover:text-[var(--text)]">
            Refresh
          </button>
        </div>

        {/* Content */}
        <div className="t-panel p-3 sm:p-4">
          {loading ? (
            <p className="text-xs text-[var(--text-dim)]">Loading...</p>
          ) : tab === "live" && events.length === 0 ? (
            <p className="text-xs text-[var(--text-dim)]">No events yet. System will log at next scheduled scan (22:00 UTC or 08:00-10:30 UTC).</p>
          ) : tab === "backtest" && btTrades.length === 0 ? (
            <p className="text-xs text-[var(--text-dim)]">No backtest results in DB. Run a backtest first.</p>
          ) : tab === "live" ? (
            <div className="space-y-1 max-h-[700px] overflow-auto">
              {events.map((e) => (
                <div key={e.id} className="flex flex-wrap sm:flex-nowrap items-start gap-2 sm:gap-3 py-1.5 border-b border-[var(--border)] text-xs">
                  <span className="text-[var(--text-dim)] min-w-[120px] shrink-0">
                    {e.timestamp ? new Date(e.timestamp).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}
                  </span>
                  <span className="min-w-[50px] shrink-0" style={{ color: stratColor(e.strategy) }}>
                    {stratLabel(e.strategy)}
                  </span>
                  <span className="font-semibold min-w-[100px] shrink-0" style={{ color: eventColor(e.event_type) }}>
                    {e.event_type}
                  </span>
                  {e.price && <span className="text-[var(--text)] min-w-[70px]">${e.price.toFixed(2)}</span>}
                  <span className="text-[var(--text-dim)] truncate">
                    {e.trade_ref && e.trade_ref !== "SYSTEM" && <span className="mr-2 text-[var(--blue)]">[{e.trade_ref}]</span>}
                    {e.context && Object.keys(e.context).length > 0 && (
                      <span>{Object.entries(e.context).map(([k, v]) => `${k}=${typeof v === 'number' ? (v as number).toFixed(2) : v}`).join(", ")}</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            /* Backtest journal — trade-by-trade narrative */
            <div className="space-y-2 max-h-[700px] overflow-x-auto">
              {btTrades.map((t, i) => (
                <div key={i} className="flex items-center gap-2 sm:gap-3 py-2 border-b border-[var(--border)] text-xs min-w-[600px]">
                  <span className="text-[var(--text-dim)] min-w-[80px]">{t.date}</span>
                  <span className="min-w-[50px]" style={{ color: stratColor(t.strategy) }}>{stratLabel(t.strategy)}</span>
                  <span className={`min-w-[40px] ${t.direction === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>{t.direction}</span>
                  <span className="text-[var(--text)] min-w-[60px]">${t.entry.toFixed(0)}</span>
                  <span className="text-[var(--text-dim)]">→</span>
                  <span className="text-[var(--text)] min-w-[60px]">${t.exit_price.toFixed(0)}</span>
                  <span className={`font-semibold min-w-[70px] ${t.pnl_sized >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                    ${t.pnl_sized >= 0 ? "+" : ""}{t.pnl_sized.toFixed(0)}
                  </span>
                  <span className="text-[var(--text-dim)] min-w-[40px]">{t.r_mult > 0 ? "+" : ""}{t.r_mult.toFixed(1)}R</span>
                  <span className="text-[var(--yellow)] min-w-[50px]">{t.status}</span>
                  <span className="text-[var(--text-dim)]">{t.hold_human}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
