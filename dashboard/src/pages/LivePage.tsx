import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AccountSnap,
  api,
  FunnelBucket,
  Run,
  SignalRow as SignalRowT,
  Trade,
} from "../lib/api";
import { useWsLive, WsEnvelope, WsStatus } from "../lib/ws";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { PositionCard } from "../components/PositionCard";
import { LiveChart } from "../components/LiveChart";
import { Funnel } from "../components/Funnel";
import { fmtMoney, fmtTs, colorForR } from "../lib/format";

type WsHook = {
  status: string;
  lastMessageAt: number;
  onMessage: (fn: (env: WsEnvelope) => void) => () => void;
};

// Per-leg live state, keyed by run_id.
type LegState = {
  run: Run;
  trades: Trade[];
  account: AccountSnap | null;
  funnel: FunnelBucket[];
  lastSignal: SignalRowT | null;
  lastEventAt: number; // epoch ms of last WS event seen for this leg
};

// Feed considered stale when no WS message for this many seconds.
const STALE_SECS = 60;

export function LivePage({
  // ws prop from App drives the global StatusBar; the cockpit needs BOTH legs,
  // so it opens its own listen-all subscription (no run_id filter) below.
  ws: _appWs,
}: {
  runId: string | null;
  ws: WsHook;
}) {
  void _appWs;
  const nav = useNavigate();

  // Listen-all WS — server filters by run_id when one is passed, so we pass
  // none to receive events for every live leg simultaneously.
  const cockpitWs = useWsLive(null);

  const [legs, setLegs] = useState<Record<string, LegState>>({});
  const [prices, setPrices] = useState<Record<string, number | null>>({});
  const flashTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const [, setTick] = useState(0);
  // Broker-truth live account (balance/equity/open_pnl), streamed tick-by-tick
  // from account_info.json via the WS 'account_live' channel. Account-WIDE
  // (both A+D share ONE broker account) — this is the single source of truth
  // for equity/P&L, replacing the per-leg (double-counting) DB snapshots.
  const [liveAcct, setLiveAcct] = useState<{
    balance: number | null;
    equity: number | null;
    open_pnl: number | null;
  } | null>(null);

  // 1s heartbeat so staleness / age render live.
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  // Discover the live legs (both A + D), then hydrate each with REST.
  const hydrate = useCallback(async () => {
    let runs: Run[] = [];
    try {
      runs = (await api.runs(100, "live")).filter((r) => !r.end_ts);
    } catch {
      return; // keep whatever we have
    }
    const next: Record<string, LegState> = {};
    await Promise.all(
      runs.map(async (run) => {
        const [tr, sigs, fn, acc] = await Promise.all([
          api.runTrades(run.run_id, "open").catch(() => ({ items: [] as Trade[] })),
          api.signalsRecent({ run_id: run.run_id, limit: 1 }).catch(() => [] as SignalRowT[]),
          api.funnel(run.run_id).catch(() => ({ buckets: [] as FunnelBucket[] })),
          api.accountLatest(run.run_id).catch(() => ({ items: [] as AccountSnap[] })),
        ]);
        next[run.run_id] = {
          run,
          trades: tr.items,
          account: acc.items?.[0] ?? null,
          funnel: fn.buckets,
          lastSignal: sigs[0] ?? null,
          lastEventAt: 0,
        };
      })
    );
    setLegs((prev) => {
      // Preserve any lastEventAt we already tracked from the WS stream.
      const merged: Record<string, LegState> = {};
      for (const [id, ls] of Object.entries(next)) {
        merged[id] = { ...ls, lastEventAt: prev[id]?.lastEventAt ?? 0 };
      }
      return merged;
    });
  }, []);

  // Initial hydrate + slow poll to detect a freshly-started/ended leg
  // (run list is not part of the WS feed).
  useEffect(() => {
    hydrate();
    const t = setInterval(hydrate, 30_000);
    return () => clearInterval(t);
  }, [hydrate]);

  // One-time price seed on mount per distinct symbol so the P&L band isn't
  // blank before the first WS `price` push arrives. No interval — the WS
  // `price` channel drives all subsequent updates in real time.
  useEffect(() => {
    let cancelled = false;
    const symbols = Array.from(
      new Set(Object.values(legs).map((l) => `${l.run.symbol}|${l.run.timeframe}`))
    );
    if (symbols.length === 0) return;
    void Promise.all(
      symbols.map(async (key) => {
        const [sym, tf] = key.split("|");
        try {
          const bars = await api.bars(sym, tf);
          const last = bars[bars.length - 1];
          if (!cancelled && last) {
            setPrices((prev) => (prev[sym] != null ? prev : { ...prev, [sym]: last.close }));
          }
        } catch {
          /* WS price will fill this in */
        }
      })
    );
    return () => {
      cancelled = true;
    };
  }, [legs]);

  // Live WS updates — route each event to the leg it belongs to.
  useEffect(() => {
    return cockpitWs.onMessage((env) => {
      const now = Date.now();

      // Real-time broker quote — run_id is null on `price` envelopes, so this
      // must run BEFORE the run_id guard below. Keyed by symbol, prefer mid.
      if (env.channel === "price") {
        const p = env.payload as Record<string, unknown>;
        const symbol = typeof p.symbol === "string" ? p.symbol : null;
        const mid =
          typeof p.mid === "number"
            ? p.mid
            : typeof p.bid === "number"
            ? p.bid
            : null;
        if (symbol && mid != null) {
          setPrices((prev) => ({ ...prev, [symbol]: mid }));
        }
        return;
      }

      // Broker-truth live account — run_id null (account-wide). Before guard.
      if (env.channel === "account_live") {
        const p = env.payload as Record<string, unknown>;
        setLiveAcct({
          balance: typeof p.balance === "number" ? p.balance : null,
          equity: typeof p.equity === "number" ? p.equity : null,
          open_pnl: typeof p.open_pnl === "number" ? p.open_pnl : null,
        });
        return;
      }

      const rid = env.run_id;
      if (!rid) return;

      if (env.channel === "signal") {
        const sig = env.payload as Record<string, unknown>;
        const signalId = Number(sig.signal_id);
        setLegs((prev) => {
          const leg = prev[rid];
          if (!leg) return prev;
          const row: SignalRowT = {
            signal_id: signalId,
            run_id: String(sig.run_id ?? rid),
            ts: String(sig.ts ?? env.ts),
            status: String(sig.status ?? ""),
            reason: (sig.reason as string | null) ?? null,
            zone_id: (sig.zone_id as number | null) ?? null,
            detail: null,
          };
          const status = row.status;
          const buckets = prev[rid].funnel;
          const exists = buckets.find((b) => b.status === status);
          const nextFunnel = exists
            ? buckets.map((b) =>
                b.status === status ? { ...b, count: b.count + 1 } : b
              )
            : [...buckets, { status, count: 1 }];
          return {
            ...prev,
            [rid]: { ...leg, lastSignal: row, funnel: nextFunnel, lastEventAt: now },
          };
        });
        // brief flash bookkeeping
        const existing = flashTimers.current.get(signalId);
        if (existing) clearTimeout(existing);
        flashTimers.current.set(
          signalId,
          setTimeout(() => flashTimers.current.delete(signalId), 800)
        );
      }

      if (env.channel === "trade") {
        setLegs((prev) => {
          if (!prev[rid]) return prev;
          return { ...prev, [rid]: { ...prev[rid], lastEventAt: now } };
        });
        // Trade lifecycle changed — refetch just this leg's open trades.
        api
          .runTrades(rid, "open")
          .then((tr) =>
            setLegs((prev) =>
              prev[rid]
                ? { ...prev, [rid]: { ...prev[rid], trades: tr.items } }
                : prev
            )
          )
          .catch(() => {});
      }

      if (env.channel === "account") {
        const p = env.payload as Record<string, unknown>;
        setLegs((prev) => {
          const leg = prev[rid];
          if (!leg) return prev;
          return {
            ...prev,
            [rid]: {
              ...leg,
              lastEventAt: now,
              account: {
                snap_id: Number(p.snap_id ?? 0),
                ts: String(p.ts ?? env.ts),
                balance: (p.balance as number | null) ?? null,
                equity: (p.equity as number | null) ?? null,
                open_pnl: (p.open_pnl as number | null) ?? null,
                open_position: (p.open_position as number | null) ?? null,
              },
            },
          };
        });
      }
    });
  }, [cockpitWs]);

  const legList = useMemo(
    () =>
      Object.values(legs).sort((a, b) =>
        (a.run.strategy_id ?? "").localeCompare(b.run.strategy_id ?? "")
      ),
    [legs]
  );

  // unrealR from freshest streamed price: (current - entry) * side / risk_units.
  const unrealFor = useCallback(
    (t: Trade, symbol: string): number | null => {
      const cur = prices[symbol];
      if (cur == null || !t.risk_units) return null;
      return ((cur - t.entry_price) * t.side) / t.risk_units;
    },
    [prices]
  );

  // Live $ unrealized for one trade: (current - entry) * side * qty * contract.
  // qty stored in raw_features.qty_lots; contract 100 for XAU. Falls back null
  // when no live price. This is broker-truth-ish (matches MT5 profit sans
  // commission/swap) and updates on every price tick.
  const unrealUsdFor = useCallback(
    (t: Trade, symbol: string): number | null => {
      const cur = prices[symbol];
      if (cur == null) return null;
      const rawQty = Number(
        (t.raw_features as Record<string, unknown> | null)?.["qty_lots"]
      );
      const lots = Number.isFinite(rawQty) && rawQty > 0 ? rawQty : null;
      if (lots == null) return null;
      const contract = symbol.startsWith("XAU") ? 100 : 100_000;
      return (cur - t.entry_price) * t.side * lots * contract;
    },
    [prices]
  );

  // ── Account KPIs. CRITICAL: A and D share ONE broker account — both legs'
  // snapshots report the SAME account-wide balance/equity/open_pnl. So we take
  // the SINGLE latest snapshot (max ts), NOT a sum (summing double-counts).
  // Only open POSITIONS are genuinely per-leg and get aggregated.
  const combined = useMemo(() => {
    // Pick the freshest account snapshot across legs (they mirror one account).
    let latest: AccountSnap | null = null;
    for (const l of legList) {
      const a = l.account;
      if (!a) continue;
      if (latest == null || (a.ts && latest.ts && a.ts > latest.ts)) latest = a;
    }
    const positions = legList.reduce((s, l) => s + l.trades.length, 0);

    // Live open P&L: prefer summing per-trade live $ from streamed price
    // (fresher than the bar-close DB snapshot). Fall back to snapshot open_pnl.
    let livePnl = 0;
    let haveLive = false;
    for (const l of legList) {
      for (const t of l.trades) {
        const u = unrealUsdFor(t, l.run.symbol);
        if (u != null) {
          livePnl += u;
          haveLive = true;
        }
      }
    }

    // Authority order for account P&L / equity / balance:
    //   1. liveAcct (broker account_info.json, streamed, tick-by-tick, truth)
    //   2. per-trade live $ summed from streamed price (if lots known)
    //   3. latest DB snapshot (bar-close, may be stale) — last resort
    const equity = liveAcct?.equity ?? latest?.equity ?? null;
    const balance = liveAcct?.balance ?? latest?.balance ?? null;
    let openPnl: number | null;
    let live: boolean;
    if (liveAcct?.open_pnl != null) {
      openPnl = liveAcct.open_pnl;
      live = true;
    } else if (haveLive) {
      openPnl = livePnl;
      live = true;
    } else {
      openPnl = latest?.open_pnl ?? null;
      live = false;
    }
    return { equity, balance, openPnl, openPnlLive: live, positions, snapTs: latest?.ts ?? null };
  }, [legList, unrealUsdFor, liveAcct]);

  const totalUnrealR = useMemo(() => {
    let sum = 0;
    let any = false;
    for (const l of legList) {
      for (const t of l.trades) {
        const u = unrealFor(t, l.run.symbol);
        if (u != null) {
          sum += u;
          any = true;
        }
      }
    }
    return any ? sum : null;
  }, [legList, unrealFor]);

  const openPnlTone =
    combined.openPnl == null
      ? "neutral"
      : combined.openPnl >= 0
      ? "bull"
      : "bear";

  const now = Date.now();

  return (
    <div className="h-full overflow-auto flex flex-col gap-3 p-3">
      {/* ── 1. Health / connection bar (thin) ── */}
      <HealthBar
        status={cockpitWs.status as WsStatus}
        lastMessageAt={cockpitWs.lastMessageAt}
        legs={legList}
        now={now}
      />

      {/* ── Live XAU price ticker — streams every tick over WS ── */}
      <LivePriceTicker price={prices["XAUUSD.ecn"] ?? null} lastMessageAt={cockpitWs.lastMessageAt} now={now} />

      {/* ── 2. P&L HERO — am I up or down, right now ── */}
      <PnlHero
        equity={combined.equity}
        balance={combined.balance}
        openPnl={combined.openPnl}
        totalUnrealR={totalUnrealR}
        positions={combined.positions}
        legs={legList}
        tone={openPnlTone}
      />

      {/* ── 3. OPEN POSITIONS — the main event, above the fold ── */}
      <Pane
        title="Open Positions"
        subtitle={combined.positions > 0 ? `${combined.positions} live across A+D` : ""}
        right={
          combined.positions > 0 ? (
            <Pill tone="bull" glow>
              <span className="text-bull">●</span> LIVE
            </Pill>
          ) : undefined
        }
        className="shrink-0"
      >
        {combined.positions === 0 ? (
          <EmptyState
            icon="⌖"
            title="No open positions"
            body="Both legs flat. Watch the gate heartbeat below to confirm the system is still evaluating."
          />
        ) : (
          <div className="p-3 space-y-4">
            {legList
              .filter((l) => l.trades.length > 0)
              .map((l) => (
                <div key={l.run.run_id} className="space-y-2">
                  <div className="flex items-center gap-2 px-0.5">
                    <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
                      {legLabel(l)}
                    </span>
                    <span className="text-ds-xs text-ink-muted font-mono">
                      {l.trades.length} open
                    </span>
                  </div>
                  {l.trades.map((t) => {
                    const cur = prices[l.run.symbol] ?? null;
                    const u = unrealFor(t, l.run.symbol);
                    // Winning/losing state instantly readable via left-border + tint.
                    const stateCls =
                      u == null
                        ? "border-l-2 border-l-line-base"
                        : u > 0
                        ? "border-l-2 border-l-bull bg-bull/[0.04]"
                        : u < 0
                        ? "border-l-2 border-l-bear bg-bear/[0.04]"
                        : "border-l-2 border-l-line-base";
                    return (
                      <div key={t.trade_id} className={`rounded-ds ${stateCls}`}>
                        <PositionCard
                          trade={t}
                          currentPrice={cur}
                          unrealR={u}
                          onClick={() => nav(`/journal?trade=${t.trade_id}`)}
                        />
                      </div>
                    );
                  })}
                </div>
              ))}
          </div>
        )}
      </Pane>

      {/* ── 4. Chart — demoted: small + collapsible, below positions ── */}
      <CollapsibleChart />

      {/* ── 5. Gate heartbeat — live funnel per leg ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 shrink-0">
        {legList.length === 0 ? (
          <Pane title="Gate Heartbeat">
            <EmptyState
              icon="◇"
              title="No live legs"
              body="Waiting for a live run to appear. The runner publishes gate events on every bar."
            />
          </Pane>
        ) : (
          legList.map((l) => {
            const age = l.lastEventAt ? Math.round((now - l.lastEventAt) / 1000) : -1;
            const total = l.funnel.reduce((s, b) => s + b.count, 0);
            return (
              <Pane
                key={l.run.run_id}
                title={legLabel(l)}
                subtitle={`${l.run.symbol} · ${l.run.timeframe}`}
                right={
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ds-dot ${
                        age < 0 ? "bg-ink-muted" : age > STALE_SECS ? "bg-warn text-warn" : "bg-bull text-bull"
                      }`}
                    />
                    <span className="text-ds-xs text-ink-muted font-mono">
                      {age < 0 ? "no event yet" : `+${age}s`}
                    </span>
                  </span>
                }
              >
                <Funnel buckets={l.funnel} total={total} />
                {l.lastSignal && (
                  <div className="px-3 pb-2 text-ds-xs text-ink-muted">
                    last{" "}
                    <span className="text-ink-secondary">
                      {l.lastSignal.status.replace(/^GATE_/, "").toLowerCase()}
                    </span>{" "}
                    <span className="font-mono">{fmtTs(l.lastSignal.ts).slice(11)}</span>
                  </div>
                )}
              </Pane>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── P&L HERO: the "am I up or down right now" band. ──
// Open P&L is the focal point — biggest + colored. Equity leads, the rest
// (balance / positions / legs) are smaller secondary stats.
function PnlHero({
  equity,
  balance,
  openPnl,
  totalUnrealR,
  positions,
  legs,
  tone,
}: {
  equity: number | null;
  balance: number | null;
  openPnl: number | null;
  totalUnrealR: number | null;
  positions: number;
  legs: LegState[];
  tone: "bull" | "bear" | "neutral";
}) {
  const pnlColor =
    openPnl == null
      ? "text-ink-muted"
      : openPnl > 0
      ? "text-bull"
      : openPnl < 0
      ? "text-bear"
      : "text-ink-secondary";
  const sign = openPnl != null && openPnl > 0 ? "+" : "";
  const rColor = colorForR(totalUnrealR);

  return (
    <div
      className={`
        shrink-0 rounded-ds border bg-bg-surface shadow-ds-card
        px-4 py-3
        ${
          tone === "bull"
            ? "border-bull/30"
            : tone === "bear"
            ? "border-bear/30"
            : "border-line-subtle"
        }
      `}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        {/* Equity — leads */}
        <div className="min-w-0">
          <div className="text-ds-xs uppercase tracking-wide text-ink-muted">
            Equity · A+D
          </div>
          <div className="text-ds-3xl font-semibold font-mono leading-none text-ink-primary">
            {fmtMoney(equity)}
          </div>
          <div className="mt-1 text-ds-xs text-ink-secondary">
            <span className="text-ink-muted">bal</span>{" "}
            <span className="font-mono">{fmtMoney(balance)}</span>
          </div>
        </div>

        {/* Open P&L — the focal point: biggest + colored, $ and R */}
        <div className="min-w-0 flex-1 flex flex-col items-start sm:items-end">
          <div className="text-ds-xs uppercase tracking-wide text-ink-muted">
            Open P&amp;L
          </div>
          <div
            className={`text-ds-3xl font-bold font-mono leading-none ${pnlColor}`}
          >
            {openPnl == null ? "—" : `${sign}${fmtMoney(openPnl, 2)}`}
          </div>
          <div className="mt-1 text-ds-sm font-mono">
            {totalUnrealR == null ? (
              <span className="text-ink-muted">no live price</span>
            ) : (
              <span className={rColor}>
                {totalUnrealR >= 0 ? "+" : ""}
                {totalUnrealR.toFixed(2)}R unrealised
              </span>
            )}
          </div>
        </div>

        {/* Secondary stats */}
        <div className="flex items-end gap-6">
          <HeroStat label="Open Pos" value={String(positions)} />
          <HeroStat
            label="Legs Live"
            value={String(legs.length)}
            tone={legs.length > 0 ? "bull" : "neutral"}
            sub={legs.map((l) => shortLeg(l)).join(" · ") || "none"}
          />
        </div>
      </div>
    </div>
  );
}

function HeroStat({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "bull" | "neutral";
}) {
  return (
    <div className="min-w-0">
      <div className="text-ds-xs uppercase tracking-wide text-ink-muted">
        {label}
      </div>
      <div
        className={`text-ds-xl font-semibold font-mono leading-tight ${
          tone === "bull" ? "text-bull" : "text-ink-primary"
        }`}
      >
        {value}
      </div>
      {sub && (
        <div className="mt-0.5 text-ds-xs text-ink-muted truncate max-w-[10rem]">
          {sub}
        </div>
      )}
    </div>
  );
}

// ── Chart: demoted below positions — small + collapsible so it never dominates. ──
function CollapsibleChart() {
  const [open, setOpen] = useState(false);
  return (
    <Pane
      title="XAU/USD · M15"
      subtitle="OANDA feed · real-time"
      className="shrink-0"
      right={
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-1 rounded-ds-sm border border-line-subtle px-1.5 py-0.5 text-ds-xs text-ink-secondary hover:border-line-base hover:text-ink-primary transition-colors duration-ds"
        >
          {open ? "Collapse ▲" : "Expand ▼"}
        </button>
      }
    >
      {open ? (
        <div className="h-[280px]">
          <LiveChart symbol="OANDA:XAUUSD" interval="15" />
        </div>
      ) : (
        <div className="px-3 py-2 text-ds-xs text-ink-muted">
          Chart collapsed · expand to view the M15 candles.
        </div>
      )}
    </Pane>
  );
}

// ── Live price ticker — big, flashes green/red on every tick ──
function LivePriceTicker({
  price,
  lastMessageAt,
  now,
}: {
  price: number | null;
  lastMessageAt: number;
  now: number;
}) {
  const prevRef = useRef<number | null>(null);
  const [dir, setDir] = useState<"up" | "down" | "flat">("flat");
  const [flashKey, setFlashKey] = useState(0);

  useEffect(() => {
    if (price == null) return;
    const prev = prevRef.current;
    if (prev != null && price !== prev) {
      setDir(price > prev ? "up" : "down");
      setFlashKey((k) => k + 1); // retrigger flash animation
    }
    prevRef.current = price;
  }, [price]);

  const age = lastMessageAt ? Math.round((now - lastMessageAt) / 1000) : -1;
  const color =
    dir === "up" ? "text-bull" : dir === "down" ? "text-bear" : "text-ink-primary";
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "·";

  return (
    <div className="flex items-center justify-between gap-3 shrink-0 rounded-ds border border-line-subtle bg-bg-surface px-4 py-3">
      <div className="flex items-center gap-3">
        <span className="text-ds-xs uppercase tracking-[1.4px] text-ink-muted">
          XAU/USD
        </span>
        <span
          key={flashKey}
          className={`font-mono text-ds-2xl font-bold tabular-nums ${color} ds-flash`}
        >
          {price == null ? "—" : price.toFixed(2)}
        </span>
        <span className={`text-ds-md ${color}`}>{arrow}</span>
      </div>
      <span className="inline-flex items-center gap-1.5 text-ds-xs text-ink-muted">
        <span
          className={`w-1.5 h-1.5 rounded-full ds-dot ${
            age >= 0 && age <= 5 ? "bg-bull text-bull" : "bg-warn text-warn"
          }`}
        />
        {age < 0 ? "waiting for tick" : `updated ${age}s ago`}
      </span>
    </div>
  );
}

// ── Health bar: at-a-glance feed liveness ──
function HealthBar({
  status,
  lastMessageAt,
  legs,
  now,
}: {
  status: WsStatus;
  lastMessageAt: number;
  legs: LegState[];
  now: number;
}) {
  const age = lastMessageAt ? Math.round((now - lastMessageAt) / 1000) : -1;
  // Dead feed = socket not open, OR open but silent past the stale window.
  const dead = status !== "open" || (age >= 0 && age > STALE_SECS);
  const stale = status === "open" && age >= 0 && age > STALE_SECS;
  const dotCls = dead
    ? "bg-bear text-bear"
    : stale
    ? "bg-warn text-warn"
    : "bg-bull text-bull";
  const tone: "bull" | "bear" | "warn" = dead ? "bear" : stale ? "warn" : "bull";
  const label = status !== "open" ? status.toUpperCase() : stale ? "STALE" : "LIVE";

  return (
    <div className="flex items-center justify-between gap-3 shrink-0 rounded-ds border border-line-subtle bg-bg-surface px-3 py-2">
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ds-dot ${dotCls}`} />
          <Pill tone={tone} glow={tone !== "warn"}>
            {label}
          </Pill>
        </span>
        <span className="text-ds-xs text-ink-muted">
          feed{" "}
          <span className="text-ink-secondary font-mono">
            {age < 0 ? "—" : `+${age}s`}
          </span>
          {age >= 0 && age > STALE_SECS && (
            <span className="text-warn"> · no data &gt;{STALE_SECS}s</span>
          )}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {legs.length === 0 ? (
          <span className="text-ds-xs text-ink-muted">no live legs detected</span>
        ) : (
          legs.map((l) => {
            const legAge = l.lastEventAt ? Math.round((now - l.lastEventAt) / 1000) : -1;
            const legStale = legAge < 0 || legAge > STALE_SECS;
            return (
              <span
                key={l.run.run_id}
                className="inline-flex items-center gap-1.5 rounded-ds-sm border border-line-subtle px-1.5 py-0.5"
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ds-dot ${
                    legStale ? "bg-warn text-warn" : "bg-bull text-bull"
                  }`}
                />
                <span className="text-ds-xs text-ink-secondary">{shortLeg(l)}</span>
                <span className="text-ds-xs text-ink-muted font-mono">
                  {legAge < 0 ? "idle" : `+${legAge}s`}
                </span>
              </span>
            );
          })
        )}
      </div>
    </div>
  );
}

// Human label for a leg (prefer the persisted trade `leg`, else strategy id).
function legLabel(l: LegState): string {
  const legTag = l.trades[0]?.leg;
  if (legTag) return `Leg ${legTag}`;
  return l.run.strategy_id ?? l.run.run_ref;
}

function shortLeg(l: LegState): string {
  const legTag = l.trades[0]?.leg;
  if (legTag) return String(legTag);
  const sid = l.run.strategy_id ?? "";
  const m = sid.match(/_([a-z])$/i);
  return m ? m[1].toUpperCase() : sid.slice(-4) || l.run.run_ref.slice(-4);
}

function EmptyState({
  icon,
  title,
  body,
}: {
  icon: string;
  title: string;
  body: string;
}) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6 py-10">
      <div className="text-3xl text-ink-muted mb-2">{icon}</div>
      <div className="text-ds-md font-semibold text-ink-secondary">{title}</div>
      <div className="text-ds-sm text-ink-muted mt-1 max-w-xs">{body}</div>
    </div>
  );
}
