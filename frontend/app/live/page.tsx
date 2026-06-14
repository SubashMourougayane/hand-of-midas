"use client";
import { useMemo } from "react";
import { TrendingUp, TrendingDown, Shield, Clock } from "lucide-react";
import { useInstrument } from "@/lib/instrument";
import type { ServiceKey } from "@/lib/client";
import { useLiveStream } from "@/lib/hooks";
import {
  PageHeader,
  Card,
  Stat,
  Badge,
  StatusDot,
  EmptyState,
} from "@/components/ui";
import { SystemMode } from "@/components/live/SystemMode";
import { MicroWindows } from "@/components/live/MicroWindows";
import { SweepProximity } from "@/components/live/SweepProximity";

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

interface LivePayload {
  state?: LiveState;
  scan?: ScanStatus;
}

export default function LivePage() {
  const { instrument } = useInstrument();
  const svc = instrument as ServiceKey;

  const { data, reconnecting, lastUpdate } = useLiveStream<LivePayload>(svc);
  const state = data?.state ?? null;
  const scan = data?.scan ?? null;
  const error = reconnecting ? "Stream disconnected, reconnecting…" : "";

  // Format lastUpdate as a wall-clock time string for the header
  const lastUpdateLabel = useMemo(() => {
    if (!lastUpdate) return "";
    return new Date(lastUpdate).toLocaleTimeString();
  }, [lastUpdate]);

  const stratColor = (s: string) =>
    s.includes("alpha_sweep") ? "var(--color-info)" : s === "mean_rev" ? "var(--color-win)" : "var(--color-warn)";
  const stratLabel = (s: string) =>
    s.includes("alpha_sweep") ? "Alpha" : s === "mean_rev" ? "MRev" : "Cross";

  const symbol = instrument === "oil" || instrument === "oil-micro" ? "BCO/USD" : "XAU/USD";

  return (
    <div className="p-3 sm:p-6 max-w-[1280px] mx-auto">
      <PageHeader
        title="Live"
        description={`Real-time trading dashboard — ${symbol}`}
        actions={
          <div className="flex items-center gap-3">
            {state?.scheduler_active ? (
              <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.8px] text-[var(--color-win)]">
                <StatusDot tone="win" pulse size={6} />
                Scheduler active
              </span>
            ) : null}
            {lastUpdateLabel ? (
              <span className="num text-[10px] text-[var(--color-text-muted)]">
                Updated · {lastUpdateLabel}
              </span>
            ) : null}
          </div>
        }
      />

        {/* System Mode */}
        <SystemMode hasPositions={(state?.db_positions?.length || state?.oanda_positions?.length || 0) > 0} />

        {/* Sweep Proximity (Gold Macro / Oil Macro only — Micro has different scan-status shape) */}
        {instrument !== "micro" && instrument !== "oil-micro" && <SweepProximity scan={scan} />}
        {(instrument === "micro" || instrument === "oil-micro") && scan && <MicroWindows scan={scan as unknown as Record<string, unknown>} />}

        {error ? (
          <Card padded className="mb-4 border-[var(--color-loss)]/40 bg-[var(--color-loss)]/5">
            <p className="text-[12px] text-[var(--color-loss)]">Backend disconnected: {error}</p>
          </Card>
        ) : null}

        {state && (
          <>
            {/* Price + Account Row */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 mb-4 hom-stagger-children">
              <Card padded lift className="hom-stagger">
                <Stat
                  label={symbol}
                  value={state.price ? state.price.mid : 0}
                  animate={!!state.price}
                  decimals={2}
                  prefix="$"
                  size="lg"
                  tone="brass"
                  hint={
                    state.price ? (
                      <span className="num">
                        Spread ${state.price.spread.toFixed(2)} ·{" "}
                        <span className={state.price.tradeable ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}>
                          {state.price.tradeable ? "Tradeable" : "Closed"}
                        </span>
                      </span>
                    ) : null
                  }
                />
              </Card>
              <Card padded lift className="hom-stagger">
                <Stat
                  label="Account NAV"
                  value={state.account?.nav_usd ?? state.account?.nav ?? 0}
                  animate
                  prefix="$"
                  size="lg"
                  hint={<span className="num">{state.account?.currency ?? "USD"}</span>}
                />
              </Card>
              <Card padded lift className="hom-stagger">
                <Stat
                  label="Open positions"
                  value={state.db_positions?.length || 0}
                  animate
                  mono={false}
                  size="lg"
                  tone={(state.db_positions?.length || 0) > 0 ? "win" : "neutral"}
                  hint={
                    (state.account?.unrealized_pl || 0) !== 0 ? (
                      <span className={`num ${(state.account?.unrealized_pl || 0) >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                        Unrealized ${state.account.unrealized_pl.toFixed(2)}
                      </span>
                    ) : (
                      <span>No positions</span>
                    )
                  }
                />
              </Card>
              <Card padded lift className="hom-stagger">
                <Stat
                  label="DD Protection"
                  value={
                    (state.dd_state?.consecutive_losses || 0) === 0 ? "Clear" :
                    (state.dd_state?.pause_counter || 0) > 0 ? "Paused" :
                    (state.dd_state?.consecutive_losses || 0) >= 3 ? "Halved" :
                    `${state.dd_state?.consecutive_losses || 0} losses`
                  }
                  size="md"
                  mono={false}
                  tone={(state.dd_state?.pause_counter || 0) > 0 ? "warn" : (state.dd_state?.consecutive_losses || 0) >= 3 ? "loss" : "neutral"}
                  hint={
                    <span className="num">
                      Streak {state.dd_state?.consecutive_losses || 0} · Equity ${state.account?.nav_usd?.toLocaleString(undefined, { maximumFractionDigits: 0 }) || "—"}
                    </span>
                  }
                />
              </Card>
            </div>

            {/* Open Positions */}
            {(state.db_positions?.length || 0) > 0 ? (
              <Card className="mb-4">
                <Card.Header>
                  <Card.Title>
                    <span className="inline-flex items-center gap-1.5"><TrendingUp size={11} /> Open Positions</span>
                  </Card.Title>
                  <span className="num text-[11px] text-[var(--color-text-muted)]">
                    {(state.db_positions || []).length}
                  </span>
                </Card.Header>
                <div className="px-3 pb-3 overflow-x-auto">
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Strategy</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Side</th>
                        <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Entry</th>
                        <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">SL</th>
                        <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">TP</th>
                        <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Units</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Since</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(state.db_positions || []).map((p) => (
                        <tr key={p.trade_ref} className="border-t border-[var(--color-border)]/60">
                          <td className="py-2">
                            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: stratColor(p.strategy) }}>
                              <span className="w-1.5 h-1.5 rounded-full" style={{ background: stratColor(p.strategy) }} aria-hidden />
                              {stratLabel(p.strategy)}
                            </span>
                          </td>
                          <td className="py-2"><Badge tone={p.side === "LONG" ? "win" : "loss"} variant="soft">{p.side}</Badge></td>
                          <td className="py-2 text-right num">${p.entry_price.toFixed(2)}</td>
                          <td className="py-2 text-right num text-[var(--color-loss)]">${p.sl?.toFixed(2) || "—"}</td>
                          <td className="py-2 text-right num text-[var(--color-win)]">${p.tp?.toFixed(2) || "—"}</td>
                          <td className="py-2 text-right num">{p.units}</td>
                          <td className="py-2 num text-[11px] text-[var(--color-text-muted)]">
                            {new Date(p.entry_time).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : null}

            {/* Recent Signals */}
            <Card className="mb-4">
              <Card.Header>
                <Card.Title>
                  <span className="inline-flex items-center gap-1.5"><Clock size={11} /> Recent Signals</span>
                </Card.Title>
                <span className="num text-[11px] text-[var(--color-text-muted)]">
                  {(state.recent_signals?.length || 0)}
                </span>
              </Card.Header>
              {(state.recent_signals?.length || 0) === 0 ? (
                <EmptyState
                  title="No signals yet"
                  description={
                    instrument === "micro" || instrument === "oil-micro"
                      ? "Scanning all market hours (rolling 4hr windows)."
                      : "Waiting for 08:00–20:00 UTC (Alpha-Sweep) or 22:00 UTC (Daily Scan)."
                  }
                />
              ) : (
                <div className="px-3 pb-3 overflow-x-auto">
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Time</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Strategy</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Dir</th>
                        <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Entry</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(state.recent_signals || []).map((s, i) => (
                        <tr key={i} className="border-t border-[var(--color-border)]/60">
                          <td className="py-1.5 num text-[11px] text-[var(--color-text-muted)]">
                            {s.timestamp ? new Date(s.timestamp).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                          </td>
                          <td className="py-1.5">
                            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: stratColor(s.strategy) }}>
                              <span className="w-1.5 h-1.5 rounded-full" style={{ background: stratColor(s.strategy) }} aria-hidden />
                              {stratLabel(s.strategy)}
                            </span>
                          </td>
                          <td className="py-1.5"><Badge tone={s.direction === "long" ? "win" : "loss"} variant="soft">{s.direction.toUpperCase()}</Badge></td>
                          <td className="py-1.5 text-right num">{s.entry_price ? `$${s.entry_price.toFixed(0)}` : "—"}</td>
                          <td className="py-1.5">
                            {s.taken ? (
                              <Badge tone="win">Taken</Badge>
                            ) : (
                              <span className="text-[11px] text-[var(--color-text-muted)]">Skip · {s.skip_reason}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            {/* Recent Trades */}
            {(state.recent_trades?.length || 0) > 0 ? (
              <Card className="mb-4">
                <Card.Header>
                  <Card.Title>
                    <span className="inline-flex items-center gap-1.5"><TrendingDown size={11} /> Recent Closed Trades</span>
                  </Card.Title>
                  <span className="num text-[11px] text-[var(--color-text-muted)]">
                    {(state.recent_trades || []).length}
                  </span>
                </Card.Header>
                <div className="px-3 pb-3 overflow-x-auto">
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Strategy</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Side</th>
                        <th className="text-right py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">P&L</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Exit</th>
                        <th className="text-left py-2 text-[10px] uppercase tracking-[0.8px] text-[var(--color-text-muted)] font-medium">Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(state.recent_trades || []).map((t) => (
                        <tr key={t.trade_ref} className="border-t border-[var(--color-border)]/60">
                          <td className="py-1.5">
                            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: stratColor(t.strategy) }}>
                              <span className="w-1.5 h-1.5 rounded-full" style={{ background: stratColor(t.strategy) }} aria-hidden />
                              {stratLabel(t.strategy)}
                            </span>
                          </td>
                          <td className="py-1.5"><Badge tone={t.side === "LONG" ? "win" : "loss"} variant="soft">{t.side}</Badge></td>
                          <td className={`py-1.5 text-right num font-semibold ${(t.pnl_usd || t.pnl_gbp) >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"}`}>
                            {(t.pnl_usd || t.pnl_gbp) >= 0 ? "+" : ""}${(t.pnl_usd || t.pnl_gbp).toFixed(0)}
                          </td>
                          <td className="py-1.5 text-[11px] uppercase text-[var(--color-warn)]">{t.exit_reason}</td>
                          <td className="py-1.5 num text-[11px] text-[var(--color-text-muted)]">
                            {t.exit_time ? new Date(t.exit_time).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : null}

            {/* Schedule Info */}
            <Card>
              <Card.Header>
                <Card.Title>Trading Schedule</Card.Title>
                <span className="num text-[11px] text-[var(--color-text-muted)]">UTC</span>
              </Card.Header>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 p-3">
                <Card surface={2} padded>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.6px]" style={{ color: "var(--color-warn)" }}>Cross-Market + Mean-Rev</div>
                  <div className="num text-[12px] text-[var(--color-text-dim)] mt-1">22:00 UTC daily</div>
                  <div className="text-[11px] text-[var(--color-text-muted)] mt-0.5">Checks 6 inter-market signals + dip-buy conditions</div>
                </Card>
                <Card surface={2} padded>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.6px]" style={{ color: "var(--color-info)" }}>Alpha-Sweep</div>
                  <div className="num text-[12px] text-[var(--color-text-dim)] mt-1">08:00–20:00 UTC · every 3 min</div>
                  <div className="text-[11px] text-[var(--color-text-muted)] mt-0.5">Monitors London + NY session for Asia sweep + M3 engulfing</div>
                </Card>
                <Card surface={2} padded>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.6px] text-[var(--color-brass-hi)]">Position Monitor</div>
                  <div className="num text-[12px] text-[var(--color-text-dim)] mt-1">Every 1 min</div>
                  <div className="text-[11px] text-[var(--color-text-muted)] mt-0.5">Checks SL/TP fills, break-even stops</div>
                </Card>
              </div>
            </Card>
          </>
        )}
    </div>
  );
}


