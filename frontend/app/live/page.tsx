"use client";
import { useState, useEffect, useRef } from "react";
import Sidebar from "@/components/Sidebar";
import { Radio, TrendingUp, TrendingDown, Shield, Clock } from "lucide-react";
import { useInstrument } from "@/lib/instrument";

interface ScanStatus {
  scan_active: boolean;
  tradeable: boolean;
  price: number;
  spread: number;
  asia_high: number;
  asia_low: number;
  asia_range: number;
  bearish_sweep_level: number;
  bullish_sweep_level: number;
  dist_to_bearish: number;
  dist_to_bullish: number;
  proximity_pct: number;
  sweep_direction: string;
  sweep_detected: boolean;
  sweep_status: string;
  sweep_info: string | null;
  daily_bias: string;
  trades_today: number;
  max_trades_per_day: number;
  utc_time: string;
  skip_reasons?: string[];
}

interface LiveState {
  price: { bid: number; ask: number; mid: number; spread: number; tradeable: boolean } | null;
  account: { balance: number; nav: number; nav_usd: number; unrealized_pl: number; open_trades: number; currency: string; gbp_usd_rate: number };
  oanda_positions: Array<{ trade_id: string; units: number; price: number; unrealized_pl: number; sl: number; tp: number }>;
  db_positions?: Array<{ trade_ref: string; strategy: string; side: string; entry_price: number; sl: number; tp: number; units: number; entry_time: string }>;
  dd_state?: { consecutive_losses: number; pause_counter: number; equity: number; peak_equity: number };
  recent_signals?: Array<{ timestamp: string; strategy: string; direction: string; entry_price: number; taken: boolean; skip_reason: string }>;
  recent_trades?: Array<{ trade_ref: string; strategy: string; side: string; pnl_gbp: number; pnl_usd: number; exit_reason: string; exit_time: string }>;
  scheduler_active: boolean;
}

export default function LivePage() {
  const { apiBase, instrument } = useInstrument();
  const [state, setState] = useState<LiveState | null>(null);
  const [scan, setScan] = useState<ScanStatus | null>(null);
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState("");

  const sseConnected = useRef(false);

  useEffect(() => {
    setState(null);
    setScan(null);
    sseConnected.current = false;
    const prefix = instrument === "oil" ? "oil" : "gold";
    // SSE must bypass Next.js proxy (it buffers streaming responses)
    const sseBase = typeof window !== "undefined" && window.location.hostname === "localhost"
      ? "https://midas.subashtrades.in"
      : "";
    const url = `${sseBase}/api/${prefix}/stream`;
    let es: EventSource | null = null;
    let fallbackInterval: NodeJS.Timeout | null = null;
    let reconnectTimeout: NodeJS.Timeout | null = null;

    const connectSSE = () => {
      es = new EventSource(url);
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.state) setState(data.state);
          if (data.scan) setScan(data.scan);
          setLastUpdate(new Date().toLocaleTimeString());
          setError("");
          sseConnected.current = true;
        } catch {}
      };
      es.onerror = () => {
        sseConnected.current = false;
        setError("Stream disconnected, reconnecting...");
        es?.close();
        reconnectTimeout = setTimeout(connectSSE, 3000);
      };
    };

    connectSSE();

    // Fallback poll only if SSE hasn't delivered data
    const fallbackFetch = async () => {
      if (sseConnected.current) return;
      try {
        const [stateRes, scanRes] = await Promise.all([
          fetch(`${apiBase}/api/${prefix}/state`),
          fetch(`${apiBase}/api/${prefix}/scan-status`),
        ]);
        if (stateRes.ok) setState(await stateRes.json());
        if (scanRes.ok) {
          const d = await scanRes.json();
          if (!d.error) setScan(d);
        }
        setLastUpdate(new Date().toLocaleTimeString());
      } catch {}
    };
    fallbackInterval = setInterval(fallbackFetch, 30000);
    // Initial fetch for fast first paint (SSE takes ~5s for first push)
    fallbackFetch();

    return () => {
      es?.close();
      if (fallbackInterval) clearInterval(fallbackInterval);
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrument]);

  const stratColor = (s: string) =>
    s .includes("alpha_sweep") ? "#4fc3f7" : s === "mean_rev" ? "#00e87b" : "#ffd54f";
  const stratLabel = (s: string) =>
    s .includes("alpha_sweep") ? "ALPHA" : s === "mean_rev" ? "MEAN-REV" : "CROSS";

  return (
    <>
      <Sidebar />
      <main className="flex-1 p-3 sm:p-6 overflow-auto pt-14 md:pt-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-5 gap-2">
          <div>
            <h1 className="text-xl font-bold text-[var(--text)]">LIVE</h1>
            <p className="text-xs text-[var(--text-dim)]">Real-time trading dashboard — {instrument === "gold" ? "XAU/USD" : "BCO/USD"}</p>
          </div>
          <div className="flex items-center gap-3">
            {state?.scheduler_active && (
              <span className="flex items-center gap-1 text-[10px] text-[var(--green)]">
                <Radio size={10} className="animate-pulse" /> SCHEDULER ACTIVE
              </span>
            )}
            {lastUpdate && <span className="text-[10px] text-[var(--text-dim)]">Updated: {lastUpdate}</span>}
          </div>
        </div>

        {/* System Mode */}
        <SystemMode hasPositions={(state?.db_positions?.length || state?.oanda_positions?.length || 0) > 0} />

        {/* Sweep Proximity */}
        <SweepProximity scan={scan} />

        {error && <div className="t-panel p-3 mb-4 text-[var(--red)] text-xs">Backend disconnected: {error}</div>}

        {state && (
          <>
            {/* Price + Account Row */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <div className="t-panel p-3">
                <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">{instrument === "oil" ? "BCO/USD" : "XAU/USD"}</div>
                <div className="text-2xl font-bold text-[var(--text)] mt-1">
                  {state.price ? `$${state.price.mid.toFixed(2)}` : "—"}
                </div>
                <div className="text-[10px] text-[var(--text-dim)] mt-0.5">
                  {state.price ? `Spread: $${state.price.spread.toFixed(2)} | ${state.price.tradeable ? "Tradeable" : "CLOSED"}` : ""}
                </div>
              </div>
              <div className="t-panel p-3">
                <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">Account NAV</div>
                <div className="text-2xl font-bold text-[var(--text)] mt-1">
                  {state.account?.currency === "GBP" ? "£" : "$"}{state.account?.nav?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "—"}
                </div>
                <div className="text-[10px] text-[var(--text-dim)] mt-0.5">
                  ${state.account?.nav_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "—"} USD{state.account?.currency === "GBP" ? ` | Rate: ${state.account?.gbp_usd_rate?.toFixed(4)}` : ""}
                </div>
              </div>
              <div className="t-panel p-3">
                <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">Open Positions</div>
                <div className="text-2xl font-bold text-[var(--text)] mt-1">{state.db_positions?.length || 0}</div>
                <div className="text-[10px] mt-0.5" style={{ color: (state.account?.unrealized_pl || 0) >= 0 ? "#00e87b" : "#ff3e3e" }}>
                  {(state.account?.unrealized_pl || 0) !== 0 ? `Unrealized: ${state.account?.currency === "GBP" ? "£" : "$"}${state.account.unrealized_pl.toFixed(2)}` : "No positions"}
                </div>
              </div>
              <div className="t-panel p-3">
                <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider flex items-center gap-1">
                  <Shield size={10} /> DD Protection
                </div>
                <div className="text-lg font-bold text-[var(--text)] mt-1">
                  {(state.dd_state?.consecutive_losses || 0) === 0 ? "CLEAR" :
                    (state.dd_state?.pause_counter || 0) > 0 ? "PAUSED" :
                      (state.dd_state?.consecutive_losses || 0) >= 3 ? "HALVED" : `${state.dd_state?.consecutive_losses || 0} losses`}
                </div>
                <div className="text-[10px] text-[var(--text-dim)] mt-0.5">
                  Streak: {state.dd_state?.consecutive_losses || 0} | Equity: ${state.account?.nav_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "—"}
                </div>
              </div>
            </div>

            {/* Open Positions */}
            {(state.db_positions?.length || 0) > 0 && (
              <div className="t-panel p-3 sm:p-4 mb-4">
                <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3 flex items-center gap-2">
                  <TrendingUp size={12} /> Open Positions
                </h2>
                <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-dim)]">
                      <th className="text-left py-1">Strategy</th>
                      <th className="text-left">Side</th>
                      <th className="text-right">Entry</th>
                      <th className="text-right">SL</th>
                      <th className="text-right">TP</th>
                      <th className="text-right">Units</th>
                      <th className="text-left">Since</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(state.db_positions || []).map((p) => (
                      <tr key={p.trade_ref} className="border-t border-[var(--border)]">
                        <td className="py-1.5">
                          <span className="text-[10px] px-1.5 py-0.5 font-semibold" style={{ color: stratColor(p.strategy), background: `${stratColor(p.strategy)}15` }}>
                            {stratLabel(p.strategy)}
                          </span>
                        </td>
                        <td className={p.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}>{p.side}</td>
                        <td className="text-right">${p.entry_price.toFixed(2)}</td>
                        <td className="text-right text-[var(--red)]">${p.sl?.toFixed(2) || "—"}</td>
                        <td className="text-right text-[var(--green)]">${p.tp?.toFixed(2) || "—"}</td>
                        <td className="text-right">{p.units}</td>
                        <td className="text-[var(--text-dim)]">{new Date(p.entry_time).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </div>
            )}

            {/* Recent Signals */}
            <div className="t-panel p-3 sm:p-4 mb-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3 flex items-center gap-2">
                <Clock size={12} /> Recent Signals
              </h2>
              {(state.recent_signals?.length || 0) === 0 ? (
                <p className="text-xs text-[var(--text-dim)]">No signals yet. Waiting for 08:00-20:00 UTC (Alpha-Sweep) or 22:00 UTC (Daily Scan).</p>
              ) : (
                <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-dim)]">
                      <th className="text-left py-1">Time</th>
                      <th className="text-left">Strategy</th>
                      <th className="text-left">Dir</th>
                      <th className="text-right">Entry</th>
                      <th className="text-left">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(state.recent_signals || []).map((s, i) => (
                      <tr key={i} className="border-t border-[var(--border)]">
                        <td className="py-1 text-[var(--text-dim)]">{s.timestamp ? new Date(s.timestamp).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                        <td><span style={{ color: stratColor(s.strategy) }}>{stratLabel(s.strategy)}</span></td>
                        <td className={s.direction === "long" ? "text-[var(--green)]" : "text-[var(--red)]"}>{s.direction.toUpperCase()}</td>
                        <td className="text-right">{s.entry_price ? `$${s.entry_price.toFixed(0)}` : "—"}</td>
                        <td>
                          {s.taken ? (
                            <span className="text-[var(--green)] font-semibold">TAKEN</span>
                          ) : (
                            <span className="text-[var(--text-dim)]">Skip: {s.skip_reason}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              )}
            </div>

            {/* Recent Trades */}
            {(state.recent_trades?.length || 0) > 0 && (
              <div className="t-panel p-3 sm:p-4 mb-4">
                <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3 flex items-center gap-2">
                  <TrendingDown size={12} /> Recent Closed Trades
                </h2>
                <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-dim)]">
                      <th className="text-left py-1">Strategy</th>
                      <th className="text-left">Side</th>
                      <th className="text-right">P&L</th>
                      <th className="text-left">Exit</th>
                      <th className="text-left">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(state.recent_trades || []).map((t) => (
                      <tr key={t.trade_ref} className="border-t border-[var(--border)]">
                        <td className="py-1"><span style={{ color: stratColor(t.strategy) }}>{stratLabel(t.strategy)}</span></td>
                        <td className={t.side === "LONG" ? "text-[var(--green)]" : "text-[var(--red)]"}>{t.side}</td>
                        <td className={`text-right font-semibold ${t.pnl_gbp >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                          £{t.pnl_gbp >= 0 ? "+" : ""}{t.pnl_gbp.toFixed(2)}
                          <span className="text-[9px] text-[var(--text-dim)] ml-1">(${t.pnl_usd.toFixed(0)})</span>
                        </td>
                        <td className="text-[var(--yellow)]">{t.exit_reason}</td>
                        <td className="text-[var(--text-dim)]">{t.exit_time ? new Date(t.exit_time).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </div>
            )}

            {/* Schedule Info */}
            <div className="t-panel p-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3">Trading Schedule (UTC)</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                <div className="p-3 bg-[var(--bg)]">
                  <div className="font-semibold" style={{ color: "#ffd54f" }}>CROSS-MARKET + MEAN-REV</div>
                  <div className="text-[var(--text-dim)] mt-1">22:00 UTC daily</div>
                  <div className="text-[10px] text-[var(--text-dim)] mt-0.5">Checks 6 inter-market signals + dip-buy conditions</div>
                </div>
                <div className="p-3 bg-[var(--bg)]">
                  <div className="font-semibold" style={{ color: "#4fc3f7" }}>ALPHA-SWEEP</div>
                  <div className="text-[var(--text-dim)] mt-1">08:00-20:00 UTC (every 3 min)</div>
                  <div className="text-[10px] text-[var(--text-dim)] mt-0.5">Monitors London + NY session for Asia sweep + M3 engulfing</div>
                </div>
                <div className="p-3 bg-[var(--bg)]">
                  <div className="font-semibold text-[var(--text)]">POSITION MONITOR</div>
                  <div className="text-[var(--text-dim)] mt-1">Every 1 min</div>
                  <div className="text-[10px] text-[var(--text-dim)] mt-0.5">Checks SL/TP fills, break-even stops</div>
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}


function SystemMode({ hasPositions }: { hasPositions: boolean }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();
  const utcTime = utcH + utcM / 60;
  const isWeekend = now.getUTCDay() === 0 || now.getUTCDay() === 6;

  // Determine mode
  let mode: string;
  let color: string;
  let icon: string;
  let countdown: string;

  if (isWeekend) {
    mode = "MARKET CLOSED";
    color = "#9ca3b4";
    icon = "🌙";
    // Forex opens Sunday 21:00 UTC (5 PM New York)
    const sundayOpen = new Date(now);
    if (now.getUTCDay() === 6) {
      // Saturday → next day (Sunday) at 21:00 UTC
      sundayOpen.setUTCDate(now.getUTCDate() + 1);
    } else {
      // Sunday → today at 21:00 UTC
      sundayOpen.setUTCDate(now.getUTCDate());
    }
    sundayOpen.setUTCHours(21, 0, 0, 0);
    const diff = sundayOpen.getTime() - now.getTime();
    const hrs = Math.floor(Math.max(diff, 0) / 3600000);
    const mins = Math.floor((Math.max(diff, 0) % 3600000) / 60000);
    countdown = diff > 0 ? `Opens in ${hrs}h ${mins}m` : "Opening soon...";
  } else if (hasPositions) {
    mode = "POSITION OPEN";
    color = "#00e87b";
    icon = "📈";
    countdown = "Monitoring every 1 min";
  } else if (utcTime >= 8 && utcTime <= 20) {
    mode = "SCANNING";
    color = "#4fc3f7";
    icon = "🔍";
    const minsLeft = Math.floor((20 - utcTime) * 60);
    countdown = `Alpha-Sweep active... ${Math.floor(minsLeft/60)}h ${minsLeft%60}m remaining`;
  } else if (utcTime >= 21.95 && utcTime <= 22.1) {
    mode = "DAILY SCAN";
    color = "#ffd54f";
    icon = "⚡";
    countdown = "Running Cross-Market + Mean-Rev...";
  } else {
    mode = "SLEEPING";
    color = "#9ca3b4";
    icon = "💤";
    // Next event
    let nextEvent: string;
    let hoursUntil: number;
    if (utcTime < 8) {
      hoursUntil = 8 - utcTime;
      nextEvent = "Alpha-Sweep";
    } else if (utcTime < 22) {
      hoursUntil = 22 - utcTime;
      nextEvent = "Daily scan";
    } else {
      hoursUntil = 24 - utcTime + 8;
      nextEvent = "Alpha-Sweep";
    }
    const hrs = Math.floor(hoursUntil);
    const mins = Math.floor((hoursUntil - hrs) * 60);
    countdown = `Next: ${nextEvent} in ${hrs}h ${mins}m`;
  }

  // All times in IST (UTC + 5:30)
  const IST_OFFSET = 5.5;
  const istTime = (utcTime + IST_OFFSET) % 24;

  // Sessions in IST — NY overlaps with London (18.5-21.5 IST)
  const sessions = [
    { name: "ASIA", start: 5.5, end: 13.5, color: "#9ca3b4" },
    { name: "LONDON", start: 13.5, end: 21.5, color: "#4fc3f7" },
    { name: "NEW YORK", start: 18.5, end: 24, color: "#ff8c00" },
  ];

  const tradingWindows = [
    { name: "Alpha-Sweep", start: 0, end: 2.5, color: "#4fc3f7" },
    { name: "Alpha-Sweep", start: 13.5, end: 24, color: "#4fc3f7" },
    { name: "Daily Scan", start: 3.5, end: 3.7, color: "#ffd54f" },
  ];

  return (
    <div className="t-panel p-3 mb-4">
      {/* Status row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg">{icon}</span>
          <div>
            <div className="text-xs font-bold" style={{ color }}>{mode}</div>
            <div className="text-[10px] text-[var(--text-dim)]">{countdown}</div>
          </div>
        </div>
        <div className="text-[10px] text-[var(--text-dim)]">
          {now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true, timeZone: "Asia/Kolkata" })} IST
        </div>
      </div>

      {/* 24h Timeline — hidden on mobile, shown on md+ */}
      <div className="hidden md:block relative mt-4 px-1 sm:px-3 pb-2 overflow-x-auto">
        {/* Time label above needle */}
        <div className="relative h-5 mb-1">
          <div className="absolute z-20" style={{ left: `calc(${(istTime / 24) * 100}%)`, transform: "translateX(-50%)" }}>
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: "#ff3e3e", color: "#fff" }}>
              {now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" })}
            </span>
          </div>
        </div>

        {/* Sessions row — single row, NY overlaps London */}
        <div className="relative h-11 mb-2 rounded" style={{ background: "#0d1017" }}>
          {/* NY wrap (12 AM – 2:30 AM) — active when NY session is running */}
          {(() => {
            const nyActive = istTime >= 18.5 || istTime < 2.5;
            return (
              <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
                style={{
                  left: "0%", width: `${(2.5 / 24) * 100}%`,
                  background: nyActive ? "#ff8c0018" : "#ff8c0006",
                  border: nyActive ? "1.5px solid #ff8c00" : "1px solid #ff8c0020",
                }}>
                <span className="text-[10px] font-extrabold tracking-wider" style={{ color: nyActive ? "#fff" : "#ff8c00" }}>NY</span>
              </div>
            );
          })()}
          {/* CLOSED (2:30 - 5:30 AM) */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center"
            style={{ left: `${(2.5 / 24) * 100}%`, width: `${(3 / 24) * 100}%` }}>
            <span className="text-[9px] font-extrabold tracking-wider" style={{ color: "#9ca3b4" }}>CLOSED</span>
          </div>
          {/* ASIA (5:30 AM - 1:30 PM) */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: `${(5.5 / 24) * 100}%`, width: `${(8 / 24) * 100}%`,
              background: (istTime >= 5.5 && istTime < 13.5) ? "#9ca3b418" : "#9ca3b406",
              border: (istTime >= 5.5 && istTime < 13.5) ? "1.5px solid #9ca3b4" : "1px solid #9ca3b420",
            }}>
            <span className="text-[10px] font-extrabold tracking-wider" style={{ color: (istTime >= 5.5 && istTime < 13.5) ? "#fff" : "#9ca3b4" }}>ASIA</span>
          </div>
          {/* LONDON (1:30 PM - 9:30 PM) */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: `${(13.5 / 24) * 100}%`, width: `${(5 / 24) * 100}%`,
              background: (istTime >= 13.5 && istTime < 21.5) ? "#4fc3f718" : "#4fc3f706",
              border: (istTime >= 13.5 && istTime < 21.5) ? "1.5px solid #4fc3f7" : "1px solid #4fc3f720",
              borderRight: "none", borderTopRightRadius: 0, borderBottomRightRadius: 0,
            }}>
            <span className="text-[10px] font-extrabold tracking-wider" style={{ color: (istTime >= 13.5 && istTime < 18.5) ? "#fff" : "#4fc3f7" }}>LONDON</span>
          </div>
          {/* OVERLAP zone (6:30 - 9:30 PM) — London + NY both active */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center"
            style={{
              left: `${(18.5 / 24) * 100}%`, width: `${(3 / 24) * 100}%`,
              background: (istTime >= 18.5 && istTime < 21.5) ? "linear-gradient(90deg, #4fc3f720, #ff8c0020)" : "linear-gradient(90deg, #4fc3f708, #ff8c0008)",
              borderTop: (istTime >= 18.5 && istTime < 21.5) ? "1.5px solid #e8c300" : "1px solid #e8c30030",
              borderBottom: (istTime >= 18.5 && istTime < 21.5) ? "1.5px solid #e8c300" : "1px solid #e8c30030",
            }}>
            <span className="text-[8px] font-bold tracking-wider" style={{ color: "#e8c300" }}>OVERLAP</span>
          </div>
          {/* NEW YORK (9:30 PM - midnight) */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: `${(21.5 / 24) * 100}%`, width: `${(2.5 / 24) * 100}%`,
              background: (istTime >= 21.5) ? "#ff8c0018" : "#ff8c0006",
              border: (istTime >= 21.5) ? "1.5px solid #ff8c00" : "1px solid #ff8c0020",
              borderLeft: "none", borderTopLeftRadius: 0, borderBottomLeftRadius: 0,
            }}>
            <span className="text-[10px] font-extrabold tracking-wider" style={{ color: (istTime >= 21.5) ? "#fff" : "#ff8c00" }}>NY</span>
          </div>
        </div>

        {/* Trading windows row */}
        <div className="relative h-10 mb-2 rounded" style={{ background: "#0d1017" }}>
          {tradingWindows.map(w => {
            // Alpha-Sweep is active if in ANY of its windows (wraps midnight)
            const isActive = w.name === "Alpha-Sweep"
              ? (istTime >= 13.5 || istTime <= 2.5)
              : (istTime >= w.start && istTime <= w.end);
            return (
              <div key={w.name + w.start} className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
                style={{
                  left: `${(w.start / 24) * 100}%`,
                  width: `${Math.max(((w.end - w.start) / 24) * 100, 2.5)}%`,
                  background: isActive ? `${w.color}35` : `${w.color}10`,
                  border: `1.5px solid ${isActive ? w.color : w.color + "40"}`,
                  boxShadow: isActive ? `0 0 20px ${w.color}25` : "none",
                }}>
                <span className="text-[10px] font-extrabold" style={{ color: "#fff" }}>{w.name}</span>
              </div>
            );
          })}
          {/* Position monitor dashed line */}
          <div className="absolute top-1/2 left-0 right-0 pointer-events-none" style={{ opacity: 0.2 }}>
            <div className="w-full h-[1px]" style={{ background: "repeating-linear-gradient(90deg, #00e87b 0px, #00e87b 3px, transparent 3px, transparent 7px)" }} />
          </div>
        </div>

        {/* Hour scale (IST 12h) */}
        <div className="relative h-5 mt-1">
          {Array.from({ length: 13 }).map((_, i) => {
            const h = i * 2;
            const label = h === 0 || h === 24 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`;
            return (
              <div key={h} className="absolute flex flex-col items-center" style={{ left: `${(h / 24) * 100}%`, transform: "translateX(-50%)" }}>
                <div className="w-[1px] h-1.5" style={{ background: "#333" }} />
                <span className="text-[8px] mt-0.5 whitespace-nowrap" style={{ color: "#5b6370" }}>{label}</span>
              </div>
            );
          })}
        </div>

        {/* Current time needle (spans both session rows) */}
        <div className="absolute z-10 pointer-events-none"
          style={{
            left: `calc(${(istTime / 24) * 100}% + 12px)`,
            top: "20px",
            height: "calc(100% - 44px)",
          }}>
          <div className="w-[2px] h-full mx-auto" style={{ background: "#ff3e3e", boxShadow: "0 0 6px #ff3e3e" }} />
        </div>
      </div>

      {/* Legend — desktop only */}
      <div className="hidden md:flex flex-wrap items-center gap-3 sm:gap-5 mt-2 px-3 text-[9px]" style={{ color: "#8b95a5" }}>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 rounded-sm" style={{ background: "#4fc3f715", border: "1px solid #4fc3f7" }} /> Alpha-Sweep (1:30 PM – 1:30 AM)</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 rounded-sm" style={{ background: "#ffd54f15", border: "1px solid #ffd54f" }} /> Daily Scan (3:30 AM)</span>
        <span className="flex items-center gap-1.5"><span className="w-[3px] h-3 rounded" style={{ background: "#ff3e3e" }} /> Now</span>
        <span className="flex items-center gap-1.5"><span className="w-5 h-[1px]" style={{ background: "repeating-linear-gradient(90deg, #00e87b 0px, #00e87b 3px, transparent 3px, transparent 6px)" }} /> Monitor (24/7)</span>
      </div>
    </div>
  );
}


function SweepProximity({ scan }: { scan: ScanStatus | null }) {
  const { instrument } = useInstrument();


  if (!scan) {
    return (
      <div className="t-panel p-4 mb-4" style={{ background: "#181c24" }}>
        <div className="text-[10px] text-[var(--text-dim)]">Loading sweep proximity...</div>
      </div>
    );
  }

  // Gauge is "stale" when sweep already resolved — dim everything
  const isGaugeStale = scan.sweep_status === "EXPIRED" || scan.sweep_status === "TRADED";

  // Calculate gauge position (0% = full bullish side, 100% = full bearish side)
  // Use proximity_pct from API which correctly handles "past sweep" cases
  const clampedPosition = scan.sweep_direction === "bearish"
    ? 50 + (scan.proximity_pct / 100) * 50   // bearish = right side (50-100%)
    : 50 - (scan.proximity_pct / 100) * 50;  // bullish = left side (0-50%)

  // Asia range markers within gauge
  const totalRange = scan.bearish_sweep_level - scan.bullish_sweep_level;
  const asiaLowPct = totalRange > 0
    ? ((scan.asia_low - scan.bullish_sweep_level) / totalRange) * 100
    : 20;
  const asiaHighPct = totalRange > 0
    ? ((scan.asia_high - scan.bullish_sweep_level) / totalRange) * 100
    : 80;

  // Dot color follows arc gradient at needle position (matches visual)
  // Arc: 0%=green, 40%=green, 60%=yellow, 80%=orange, 100%=red
  let dotColor: string;
  if (isGaugeStale) {
    dotColor = "#5b6370"; // gray when stale
  } else if (clampedPosition <= 20 || clampedPosition >= 80) {
    dotColor = clampedPosition >= 80 ? "#ff3e3e" : "#00e87b"; // at extremes
  } else if (clampedPosition <= 40 || clampedPosition >= 60) {
    dotColor = clampedPosition >= 60 ? "#ff8c00" : "#00e87b"; // approaching
  } else {
    dotColor = "#ffd54f"; // center = yellow (between sweeps)
  }

  // Only pulse when actively near a sweep AND gauge is live
  const distBearish = Math.abs(scan.dist_to_bearish);
  const distBullish = Math.abs(scan.dist_to_bullish);
  const closestDist = Math.min(distBearish, distBullish);
  const shouldPulse = !isGaugeStale && closestDist <= 5 && scan.sweep_status === "ACTIVE";

  // Bias badge color
  const biasColor = scan.daily_bias === "bullish" ? "#00e87b" : scan.daily_bias === "bearish" ? "#ff3e3e" : "#9ca3b4";

  // Needle angle: 0% = -90deg (left/bullish), 100% = 90deg (right/bearish)
  const needleAngle = -90 + (clampedPosition / 100) * 180;

  return (
    <div className="t-panel p-4 mb-4" style={{ background: "#181c24" }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-[10px] font-semibold text-[var(--text-dim)] uppercase tracking-wider">Sweep Proximity</h2>
        <div className="flex items-center gap-2">
          {scan.sweep_detected && (() => {
            const status = scan.sweep_status || "ACTIVE";
            const statusStyle = status === "ACTIVE"
              ? { bg: "#00e87b20", color: "#00e87b", border: "#00e87b", anim: "sweepFlash 0.8s ease-in-out infinite alternate" }
              : status === "EXPIRED"
              ? { bg: "#9ca3b415", color: "#9ca3b4", border: "#9ca3b440", anim: "none" }
              : status === "TRADED"
              ? { bg: "#4fc3f720", color: "#4fc3f7", border: "#4fc3f7", anim: "none" }
              : { bg: "#ff3e3e20", color: "#ff3e3e", border: "#ff3e3e", anim: "sweepFlash 0.8s ease-in-out infinite alternate" };
            return (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded"
                style={{ background: statusStyle.bg, color: statusStyle.color, border: `1px solid ${statusStyle.border}`, animation: statusStyle.anim }}>
                SWEEP {status} ({scan.sweep_direction.toUpperCase()})
              </span>
            );
          })()}
          {scan.skip_reasons && scan.skip_reasons.length > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded"
              style={{ background: "#ffd54f20", color: "#ffd54f", border: "1px solid #ffd54f40" }}>
              SKIP: {scan.skip_reasons.join(", ")}
            </span>
          )}
          <span className="text-[9px] text-[var(--text-dim)]">UTC {scan.utc_time}</span>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row items-center sm:items-start gap-4 sm:gap-6">
        {/* Semicircle Speedometer */}
        <div style={{ position: "relative", width: "220px", height: "130px", flexShrink: 0, opacity: isGaugeStale ? 0.4 : 1, transition: "opacity 0.5s" }}>
          {/* SVG semicircle arc */}
          <svg viewBox="0 0 200 110" style={{ width: "100%", height: "100%" }}>
            {/* Background arc */}
            <path d="M 15 100 A 85 85 0 0 1 185 100" fill="none" stroke="#1a1f2b" strokeWidth="12" strokeLinecap="round" />
            {/* Gradient arc — green to yellow to red */}
            <defs>
              <linearGradient id="sweepGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor={isGaugeStale ? "#3a3f4a" : "#00e87b"} />
                <stop offset="40%" stopColor={isGaugeStale ? "#3a3f4a" : "#00e87b"} />
                <stop offset="60%" stopColor={isGaugeStale ? "#4a4f5a" : "#ffd54f"} />
                <stop offset="80%" stopColor={isGaugeStale ? "#5a5f6a" : "#ff8c00"} />
                <stop offset="100%" stopColor={isGaugeStale ? "#6a6f7a" : "#ff3e3e"} />
              </linearGradient>
            </defs>
            <path d="M 15 100 A 85 85 0 0 1 185 100" fill="none" stroke="url(#sweepGrad)" strokeWidth="8" strokeLinecap="round" opacity="0.4" />
            {/* Active portion up to needle */}
            <path d="M 15 100 A 85 85 0 0 1 185 100" fill="none" stroke="url(#sweepGrad)" strokeWidth="8" strokeLinecap="round"
              strokeDasharray={`${clampedPosition * 2.67} 267`} />
            {/* Asia Low tick */}
            <line x1={15 + (asiaLowPct / 100) * 170} y1="92" x2={15 + (asiaLowPct / 100) * 170} y2="100" stroke={isGaugeStale ? "#3a4550" : "#4fc3f7"} strokeWidth="2" />
            {/* Asia High tick */}
            <line x1={15 + (asiaHighPct / 100) * 170} y1="92" x2={15 + (asiaHighPct / 100) * 170} y2="100" stroke={isGaugeStale ? "#3a4550" : "#4fc3f7"} strokeWidth="2" />
          </svg>

          {/* Needle */}
          <div style={{
            position: "absolute", bottom: "10px", left: "50%", transformOrigin: "bottom center",
            transform: `translateX(-50%) rotate(${needleAngle}deg)`,
            width: "2px", height: "70px",
            background: `linear-gradient(to top, ${dotColor}, transparent)`,
            transition: "transform 0.5s ease-out",
          }}>
            <div style={{
              position: "absolute", top: "0", left: "50%", transform: "translateX(-50%)",
              width: "8px", height: "8px", borderRadius: "50%", background: dotColor,
              boxShadow: shouldPulse ? `0 0 12px ${dotColor}` : `0 0 4px ${dotColor}60`,
              animation: shouldPulse ? "sweepPulse 1s ease-in-out infinite" : "none",
            }} />
          </div>

          {/* Center pivot */}
          <div style={{
            position: "absolute", bottom: "6px", left: "50%", transform: "translateX(-50%)",
            width: "10px", height: "10px", borderRadius: "50%", background: "#252a33", border: "2px solid #4b5563",
          }} />

          {/* Labels */}
          <div style={{ position: "absolute", bottom: "0", left: "4px", fontSize: "8px", color: isGaugeStale ? "#5b6370" : "#00e87b" }}>BULL</div>
          <div style={{ position: "absolute", bottom: "0", right: "4px", fontSize: "8px", color: isGaugeStale ? "#5b6370" : "#ff3e3e" }}>BEAR</div>

          {/* Price in center */}
          <div style={{ position: "absolute", bottom: "22px", left: "50%", transform: "translateX(-50%)", textAlign: "center" }}>
            <div style={{ fontSize: "16px", fontWeight: "bold", color: isGaugeStale ? "#9ca3b4" : dotColor }}>${scan.price.toFixed(2)}</div>
            <div style={{ fontSize: "8px", color: "#5b6370" }}>{String(instrument) === "oil" ? "BCO/USD" : "XAU/USD"}</div>
          </div>

          {/* Stale overlay label */}
          {isGaugeStale && (
            <div style={{ position: "absolute", top: "8px", left: "50%", transform: "translateX(-50%)", textAlign: "center" }}>
              <span className="text-[8px] font-bold px-1.5 py-0.5 rounded" style={{ background: "#1a1f2b", color: "#5b6370", border: "1px solid #333" }}>
                {scan.sweep_status === "TRADED" ? "TRADED" : "EXPIRED"}
              </span>
            </div>
          )}
        </div>

        {/* Stats panel (right side) */}
        <div className="w-full flex-1 grid grid-cols-2 gap-3">
          {(() => {
            const isOil = String(instrument) === "oil";
            const dp = isOil ? 2 : 1; // decimal places for distances
            const lp = isOil ? 2 : 0; // decimal places for levels
            return (<>
              <div className="p-2 rounded" style={{ background: "#0d1017" }}>
                <div className="text-[8px] text-[var(--text-dim)] uppercase">Bearish Sweep</div>
                <div className="text-sm font-bold" style={{ color: "#ff3e3e" }}>
                  {scan.dist_to_bearish <= 0
                    ? <><span className="text-[9px]">BREACHED</span> ${Math.abs(scan.dist_to_bearish).toFixed(dp)} past</>
                    : `$${scan.dist_to_bearish.toFixed(dp)} away`}
                </div>
                <div className="text-[8px] text-[var(--text-dim)]">Level: ${scan.bearish_sweep_level.toFixed(lp)}</div>
              </div>
              <div className="p-2 rounded" style={{ background: "#0d1017" }}>
                <div className="text-[8px] text-[var(--text-dim)] uppercase">Bullish Sweep</div>
                <div className="text-sm font-bold" style={{ color: "#00e87b" }}>
                  {scan.dist_to_bullish <= 0
                    ? <><span className="text-[9px]">BREACHED</span> ${Math.abs(scan.dist_to_bullish).toFixed(dp)} past</>
                    : `$${scan.dist_to_bullish.toFixed(dp)} away`}
                </div>
                <div className="text-[8px] text-[var(--text-dim)]">Level: ${scan.bullish_sweep_level.toFixed(lp)}</div>
              </div>
              <div className="p-2 rounded" style={{ background: "#0d1017" }}>
                <div className="text-[8px] text-[var(--text-dim)] uppercase">Daily Bias</div>
                <span className="text-xs font-bold px-2 py-0.5 rounded" style={{ color: biasColor, background: `${biasColor}15`, border: `1px solid ${biasColor}40` }}>
                  {scan.daily_bias.toUpperCase()}
                </span>
              </div>
              <div className="p-2 rounded" style={{ background: "#0d1017" }}>
                <div className="text-[8px] text-[var(--text-dim)] uppercase">Trades Today</div>
                <div className="text-sm font-bold text-[var(--text)]">{scan.trades_today} / {scan.max_trades_per_day}</div>
              </div>
              <div className="p-2 rounded" style={{ background: "#0d1017" }}>
                <div className="text-[8px] text-[var(--text-dim)] uppercase">Asia Range</div>
                <div className="text-sm font-bold text-[#4fc3f7]">${scan.asia_range.toFixed(lp)}</div>
                <div className="text-[8px] text-[var(--text-dim)]">${scan.asia_low.toFixed(lp)} – ${scan.asia_high.toFixed(lp)}</div>
              </div>
              <div className="p-2 rounded" style={{ background: "#0d1017" }}>
                <div className="text-[8px] text-[var(--text-dim)] uppercase">Sweep Status</div>
                <div className="text-sm font-bold" style={{ color:
                  scan.sweep_status === "ACTIVE" ? "#00e87b" :
                  scan.sweep_status === "TRADED" ? "#4fc3f7" :
                  scan.sweep_status === "EXPIRED" ? "#9ca3b4" : "#5b6370"
                }}>
                  {scan.sweep_status || (scan.sweep_detected ? "DETECTED" : "WAITING")}
                </div>
              </div>
            </>);
          })()}
        </div>
      </div>

      {/* Animations */}
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes sweepPulse { 0%,100% { transform: translateX(-50%) scale(1); } 50% { transform: translateX(-50%) scale(1.4); } }
        @keyframes sweepFlash { 0% { opacity: 1; } 100% { opacity: 0.4; } }
      ` }} />
    </div>
  );
}
