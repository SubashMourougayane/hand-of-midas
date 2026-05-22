"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { Radio, TrendingUp, TrendingDown, Shield, Clock } from "lucide-react";
import { useInstrument } from "@/lib/instrument";

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
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState("");

  const fetchState = async () => {
    const prefix = instrument === "oil" ? "oil" : "gold";
    try {
      const res = await fetch(`${apiBase}/api/${prefix}/state`);
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setState(data);
      setLastUpdate(new Date().toLocaleTimeString());
      setError("");
    } catch {
      setError("Connecting to backend...");
    }
  };

  useEffect(() => {
    setState(null);
    fetchState();
    const interval = setInterval(fetchState, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrument]);

  const stratColor = (s: string) =>
    s .includes("alpha_sweep") ? "#4fc3f7" : s === "mean_rev" ? "#00e87b" : "#ffd54f";
  const stratLabel = (s: string) =>
    s .includes("alpha_sweep") ? "ALPHA" : s === "mean_rev" ? "MEAN-REV" : "CROSS";

  return (
    <>
      <Sidebar />
      <main className="flex-1 p-6 overflow-auto">
        <div className="flex items-center justify-between mb-5">
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

        {error && <div className="t-panel p-3 mb-4 text-[var(--red)] text-xs">Backend disconnected: {error}</div>}

        {state && (
          <>
            {/* Price + Account Row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <div className="t-panel p-3">
                <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">XAU/USD</div>
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
                  £{state.account?.nav?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "—"}
                </div>
                <div className="text-[10px] text-[var(--text-dim)] mt-0.5">
                  ${state.account?.nav_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "—"} USD | Rate: {state.account?.gbp_usd_rate?.toFixed(4) || "—"}
                </div>
              </div>
              <div className="t-panel p-3">
                <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">Open Positions</div>
                <div className="text-2xl font-bold text-[var(--text)] mt-1">{state.db_positions?.length || 0}</div>
                <div className="text-[10px] mt-0.5" style={{ color: (state.account?.unrealized_pl || 0) >= 0 ? "#00e87b" : "#ff3e3e" }}>
                  {(state.account?.unrealized_pl || 0) !== 0 ? `Unrealized: £${state.account.unrealized_pl.toFixed(2)}` : "No positions"}
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
                  Streak: {state.dd_state?.consecutive_losses || 0} | Equity: ${(state.dd_state?.equity || 0).toFixed(0)}
                </div>
              </div>
            </div>

            {/* Open Positions */}
            {(state.db_positions?.length || 0) > 0 && (
              <div className="t-panel p-4 mb-4">
                <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3 flex items-center gap-2">
                  <TrendingUp size={12} /> Open Positions
                </h2>
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
            )}

            {/* Recent Signals */}
            <div className="t-panel p-4 mb-4">
              <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3 flex items-center gap-2">
                <Clock size={12} /> Recent Signals
              </h2>
              {(state.recent_signals?.length || 0) === 0 ? (
                <p className="text-xs text-[var(--text-dim)]">No signals yet. Waiting for 22:00 UTC (daily) or 08:00-10:30 UTC (London).</p>
              ) : (
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
              )}
            </div>

            {/* Recent Trades */}
            {(state.recent_trades?.length || 0) > 0 && (
              <div className="t-panel p-4 mb-4">
                <h2 className="text-xs font-semibold text-[var(--text-dim)] uppercase mb-3 flex items-center gap-2">
                  <TrendingDown size={12} /> Recent Closed Trades
                </h2>
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
                  <div className="text-[var(--text-dim)] mt-1">08:00-10:30 UTC (every 3 min)</div>
                  <div className="text-[10px] text-[var(--text-dim)] mt-0.5">Monitors London session for Asia sweep + M3 engulfing</div>
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
    const mondayOpen = new Date(now);
    mondayOpen.setUTCDate(now.getUTCDate() + (8 - now.getUTCDay()) % 7);
    mondayOpen.setUTCHours(0, 0, 0, 0);
    const diff = mondayOpen.getTime() - now.getTime();
    const hrs = Math.floor(diff / 3600000);
    const mins = Math.floor((diff % 3600000) / 60000);
    countdown = `Opens in ${hrs}h ${mins}m`;
  } else if (hasPositions) {
    mode = "POSITION OPEN";
    color = "#00e87b";
    icon = "📈";
    countdown = "Monitoring every 1 min";
  } else if (utcTime >= 8 && utcTime <= 10.5) {
    mode = "LONDON ACTIVE";
    color = "#4fc3f7";
    icon = "🔍";
    const minsLeft = Math.floor((10.5 - utcTime) * 60);
    countdown = `Scanning... ${minsLeft}m remaining`;
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
      nextEvent = "London session";
    } else if (utcTime < 22) {
      hoursUntil = 22 - utcTime;
      nextEvent = "Daily scan";
    } else {
      hoursUntil = 24 - utcTime + 8;
      nextEvent = "London session";
    }
    const hrs = Math.floor(hoursUntil);
    const mins = Math.floor((hoursUntil - hrs) * 60);
    countdown = `Next: ${nextEvent} in ${hrs}h ${mins}m`;
  }

  // All times in IST (UTC + 5:30)
  const IST_OFFSET = 5.5;
  const istTime = (utcTime + IST_OFFSET) % 24;

  // Sessions wrap around midnight — use start/end in IST
  const sessions = [
    { name: "ASIA", start: 5.5, end: 13.5, color: "#9ca3b4" },
    { name: "LONDON", start: 13.5, end: 21.5, color: "#4fc3f7" },
    { name: "NEW YORK", start: 18.5, end: 26.5, color: "#ff8c00" }, // wraps past 24 → render as two parts
  ];

  const tradingWindows = [
    { name: "Alpha-Sweep", start: 13.5, end: 16, color: "#4fc3f7" },
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

      {/* 24h Timeline */}
      <div className="relative mt-4 px-3 pb-2">
        {/* Time label above needle */}
        <div className="relative h-5 mb-1">
          <div className="absolute z-20" style={{ left: `calc(${(istTime / 24) * 100}%)`, transform: "translateX(-50%)" }}>
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: "#ff3e3e", color: "#fff" }}>
              {now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" })}
            </span>
          </div>
        </div>

        {/* Sessions row */}
        <div className="relative h-11 mb-2 rounded" style={{ background: "#0d1017" }}>
          {sessions.map(s => {
            const renderStart = Math.min(s.start, 24);
            const renderEnd = Math.min(s.end, 24);
            const isActive = s.end <= 24
              ? (istTime >= s.start && istTime < s.end)
              : (istTime >= s.start || istTime < (s.end - 24));
            return (
              <div key={s.name} className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
                style={{
                  left: `${(renderStart / 24) * 100}%`,
                  width: `${((renderEnd - renderStart) / 24) * 100}%`,
                  background: isActive ? `${s.color}18` : `${s.color}06`,
                  border: isActive ? `1.5px solid ${s.color}` : `1px solid ${s.color}20`,
                }}>
                <span className="text-[11px] font-extrabold tracking-wider" style={{ color: isActive ? "#fff" : s.color }}>{s.name}</span>
              </div>
            );
          })}
          {/* NY wrap (12 AM – 2:30 AM) */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
            style={{
              left: "0%", width: `${(2.5 / 24) * 100}%`,
              background: istTime < 2.5 ? "#ff8c0018" : "#ff8c0006",
              border: istTime < 2.5 ? "1.5px solid #ff8c00" : "1px solid #ff8c0020",
            }}>
            <span className="text-[11px] font-extrabold tracking-wider" style={{ color: istTime < 2.5 ? "#fff" : "#ff8c00" }}>NEW YORK</span>
          </div>
          {/* Gap (2:30 AM - 5:30 AM = market closed) */}
          <div className="absolute top-1.5 bottom-1.5 flex items-center justify-center"
            style={{ left: `${(2.5 / 24) * 100}%`, width: `${(3 / 24) * 100}%` }}>
            <span className="text-[9px] font-extrabold tracking-wider" style={{ color: "#9ca3b4" }}>CLOSED</span>
          </div>
        </div>

        {/* Trading windows row */}
        <div className="relative h-10 mb-2 rounded" style={{ background: "#0d1017" }}>
          {tradingWindows.map(w => {
            const isActive = istTime >= w.start && istTime <= w.end;
            return (
              <div key={w.name} className="absolute top-1.5 bottom-1.5 flex items-center justify-center rounded"
                style={{
                  left: `${(w.start / 24) * 100}%`,
                  width: `${Math.max(((w.end - w.start) / 24) * 100, 2.5)}%`,
                  background: isActive ? `${w.color}35` : `${w.color}10`,
                  border: isActive ? `2px solid ${w.color}` : `1px solid ${w.color}40`,
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
            const label = h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`;
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

      {/* Legend */}
      <div className="flex items-center gap-5 mt-2 px-3 text-[9px]" style={{ color: "#8b95a5" }}>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 rounded-sm" style={{ background: "#4fc3f715", border: "1px solid #4fc3f7" }} /> Alpha-Sweep (1:30–4:00 PM)</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 rounded-sm" style={{ background: "#ffd54f15", border: "1px solid #ffd54f" }} /> Daily Scan (3:30 AM)</span>
        <span className="flex items-center gap-1.5"><span className="w-[3px] h-3 rounded" style={{ background: "#ff3e3e" }} /> Now</span>
        <span className="flex items-center gap-1.5"><span className="w-5 h-[1px]" style={{ background: "repeating-linear-gradient(90deg, #00e87b 0px, #00e87b 3px, transparent 3px, transparent 6px)" }} /> Monitor (24/7)</span>
      </div>
    </div>
  );
}
