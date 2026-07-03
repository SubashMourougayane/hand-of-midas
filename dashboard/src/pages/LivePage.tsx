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
import { legName, sideLabel, gateLabel } from "../lib/labels";
import { SectionHeader } from "../components/ui/Section";
import { StatTile } from "../components/ui/StatTile";
import { PriceValue } from "../components/ui/PriceValue";

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
  // Per-ticket broker-truth live P&L + size, keyed by broker_ticket.
  const [livePos, setLivePos] = useState<
    Record<string, { unrealized_usd: number; volume: number | null; booked_usd: number | null }>
  >({});
  const flashTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  // Debounce per-leg open-trade refetch on WS trade bursts (avoid N² storm).
  const tradeRefetch = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Realized $ from trades CLOSED today (since 00:00 UTC), broker-truth. Added
  // to the open float for a genuine Day P&L (distinct from Open P&L).
  const [realizedToday, setRealizedToday] = useState<number>(0);
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
    let allRuns: Run[] = [];
    try {
      allRuns = await api.runs(200, "live");
    } catch {
      return; // keep whatever we have
    }
    const activeRuns = allRuns.filter((r) => !r.end_ts);
    // Open positions can be stranded on an ENDED run when the leg restarted
    // before re-pointing (broker still holds them; DB row's run_id lags). To
    // never hide a real open position, gather open trades for the strategy
    // across ALL its runs (active + ended) and attach to the active leg,
    // deduped by broker_ticket. (Frontend safety net for run-bookkeeping lag.)
    const runsByStrat: Record<string, Run[]> = {};
    for (const r of allRuns) (runsByStrat[r.strategy_id] ??= []).push(r);

    const next: Record<string, LegState> = {};
    await Promise.all(
      activeRuns.map(async (run) => {
        const stratRuns = runsByStrat[run.strategy_id] ?? [run];
        const [sigs, fn, acc, ...tradeLists] = await Promise.all([
          api.signalsRecent({ run_id: run.run_id, limit: 1 }).catch(() => [] as SignalRowT[]),
          api.funnel(run.run_id).catch(() => ({ buckets: [] as FunnelBucket[] })),
          api.accountLatest(run.run_id).catch(() => ({ items: [] as AccountSnap[] })),
          ...stratRuns.map((sr) =>
            api.runTrades(sr.run_id, "open").then((x) => x.items).catch(() => [] as Trade[])
          ),
        ]);
        // Dedup open trades by broker_ticket (re-adopt makes 2 rows/ticket).
        const seen = new Set<string>();
        const trades: Trade[] = [];
        for (const t of (tradeLists as Trade[][]).flat()) {
          const key = (t.broker_ticket && t.broker_ticket.trim()) || t.trade_id;
          if (seen.has(key)) continue;
          seen.add(key);
          trades.push(t);
        }
        next[run.run_id] = {
          run,
          trades,
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

  // Initial hydrate + slow poll to detect a freshly-started/ended leg. The run
  // list is NOT part of the WS feed, so this poll is discovery-only; live
  // trade/signal/account/price updates all arrive via WS in real time. 60s is
  // plenty for spotting a leg that started/stopped.
  useEffect(() => {
    hydrate();
    const t = setInterval(hydrate, 60_000);
    return () => clearInterval(t);
  }, [hydrate]);

  // Realized-today: sum broker_net_usd of trades CLOSED since 00:00 UTC today,
  // across the active live strategies. Day P&L = this + open float (below), so
  // it's genuinely distinct from Open P&L. Polled with the discovery loop.
  const hydrateRealizedToday = useCallback(async () => {
    try {
      const runsAll = await api.runs(200, "live");
      const activeStrats = new Set(
        runsAll.filter((r) => !r.end_ts).map((r) => r.strategy_id)
      );
      const runs = runsAll.filter((r) => activeStrats.has(r.strategy_id));
      const lists = await Promise.all(
        runs.map((r) =>
          api.runTrades(r.run_id, "closed", 1, 5000).then((x) => x.items).catch(() => [] as Trade[])
        )
      );
      const startOfDayUtc = new Date();
      startOfDayUtc.setUTCHours(0, 0, 0, 0);
      const cutoff = startOfDayUtc.getTime();
      const seen = new Set<string>();
      let sum = 0;
      for (const t of lists.flat()) {
        if (t.exit_timestamp == null) continue;
        if (new Date(t.exit_timestamp).getTime() < cutoff) continue;
        // Dedup by broker_ticket (A+D dual-adopt writes 2 rows) else trade_id.
        const key = (t.broker_ticket && t.broker_ticket.trim()) || t.trade_id;
        if (seen.has(key)) continue;
        seen.add(key);
        sum += t.broker_net_usd ?? 0;
      }
      setRealizedToday(sum);
    } catch {
      /* keep prior */
    }
  }, []);

  useEffect(() => {
    hydrateRealizedToday();
    const t = setInterval(hydrateRealizedToday, 60_000);
    return () => clearInterval(t);
  }, [hydrateRealizedToday]);

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

      // Per-ticket live P&L + size (broker truth) — run_id null. Before guard.
      if (env.channel === "positions_live") {
        const positions = (env.payload as any)?.positions as
          | Record<string, { unrealized_usd?: number; volume?: number | null; booked_usd?: number | null }>
          | undefined;
        if (!positions) return;
        const next: Record<string, { unrealized_usd: number; volume: number | null; booked_usd: number | null }> = {};
        for (const [ticket, p] of Object.entries(positions)) {
          if (typeof p.unrealized_usd === "number") {
            next[ticket] = {
              unrealized_usd: p.unrealized_usd,
              volume: p.volume ?? null,
              booked_usd: typeof p.booked_usd === "number" ? p.booked_usd : null,
            };
          }
        }
        setLivePos(next);
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
        // Trade lifecycle changed — refetch just this leg's open trades, but
        // DEBOUNCE: a burst of trade events (partial TP + entry + exit on both
        // legs) would otherwise fire many redundant fetches. Coalesce to one
        // fetch per leg per 4s window.
        const pending = tradeRefetch.current.get(rid);
        if (pending) clearTimeout(pending);
        tradeRefetch.current.set(
          rid,
          setTimeout(() => {
            tradeRefetch.current.delete(rid);
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
          }, 4000)
        );
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

  const feedAge = cockpitWs.lastMessageAt
    ? Math.round((now - cockpitWs.lastMessageAt) / 1000)
    : -1;
  const px = prices["XAUUSD.ecn"] ?? null;

  // Position split + aggregate risk across all open trades.
  const openTrades = legList.flatMap((l) => l.trades);
  const nLong = openTrades.filter((t) => t.side > 0).length;
  const nShort = openTrades.filter((t) => t.side < 0).length;
  const riskUsd = openTrades.reduce(
    (s, t) => s + (t.risk_units ?? 0) * 100,
    0
  );
  // Booked $ already realised on STILL-OPEN trades (partial-TP). Prefer live WS
  // booked, else the DB raw_features fallback (deal aged off the bridge). Counted
  // the same way the Trades page counts it, so the two pages stay consistent.
  const openBooked = openTrades.reduce((s, t) => {
    const lp = t.broker_ticket ? livePos[t.broker_ticket] : undefined;
    const dbBooked = Number(
      (t.raw_features as Record<string, unknown> | null)?.["partial_booked_usd"]
    );
    const booked =
      lp?.booked_usd != null && Math.abs(lp.booked_usd) > 0.001
        ? lp.booked_usd
        : Number.isFinite(dbBooked)
        ? dbBooked
        : 0;
    return s + booked;
  }, 0);
  // Day P&L = realized today (closed) + booked-on-open partials + open float.
  // (NOT equity−balance, which is just the float and duplicates Open P&L.)
  const openFloat = combined.openPnl;
  const dayPnl =
    openFloat != null
      ? realizedToday + openBooked + openFloat
      : realizedToday + openBooked || null;
  const strategiesLive = legList.length;

  // THE number a human wants: am I up since I funded the account?
  // Baseline = the 10K deposit the track record was reset to (2026-07-01).
  // Total Return = current equity − deposit. Edit if the funded amount changes.
  const DEPOSIT_BASELINE = 10000;
  const totalReturn =
    combined.equity != null ? combined.equity - DEPOSIT_BASELINE : null;
  const totalReturnPct =
    totalReturn != null ? (totalReturn / DEPOSIT_BASELINE) * 100 : null;
  const trTone =
    totalReturn == null ? "neutral" : totalReturn >= 0 ? "bull" : "bear";

  return (
    <div className="h-full overflow-auto flex flex-col gap-6 px-4 sm:px-6 py-5 w-full">
      {/* ══ SECTION 01 · account status ══ */}
      <section className="flex flex-col gap-3">
        <SectionHeader
          index="01"
          title="Account Status"
          question="Where do we stand right now?"
          right={
            <span className="font-mono text-ds-xs text-ink-muted">
              {feedAge < 0 ? "—" : `updated ${feedAge}s ago`}
            </span>
          }
        />

        {/* ── HERO: the two numbers that actually matter ── */}
        {/* Equity = what the account is worth now. Total Return = up/down since
            the 10K deposit. Everything else is supporting context below. */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          <div className="glass-strong rounded-ds-lg px-5 py-4 flex flex-col justify-center">
            <div className="text-ds-xs uppercase tracking-wide text-ink-muted">Equity</div>
            <div className="mt-1 font-mono font-semibold text-ds-3xl leading-none text-ink-primary tabular-nums">
              ${fmtMoneyBare(combined.equity)}
            </div>
            <div className="mt-1.5 text-ds-xs text-ink-muted">
              balance <span className="font-mono text-ink-secondary">${fmtMoneyBare(combined.balance)}</span>
              {openFloat != null && (
                <>
                  {" · "}float{" "}
                  <span className={`font-mono ${openFloat >= 0 ? "text-bull" : "text-bear"}`}>
                    {openFloat >= 0 ? "+" : "−"}${fmtMoneyBare(openFloat)}
                  </span>
                </>
              )}
            </div>
          </div>
          <div className={`glass-strong rounded-ds-lg px-5 py-4 flex flex-col justify-center border-l-2 ${
            trTone === "bull" ? "border-l-bull" : trTone === "bear" ? "border-l-bear" : "border-l-line-base"
          }`}>
            <div className="text-ds-xs uppercase tracking-wide text-ink-muted">Total Return · all-time since $10k</div>
            <div className={`mt-1 font-mono font-bold text-ds-3xl leading-none tabular-nums ${
              trTone === "bull" ? "text-bull" : trTone === "bear" ? "text-bear" : "text-ink-primary"
            }`}>
              {totalReturn == null ? "—" : `${totalReturn >= 0 ? "+" : "−"}$${fmtMoneyBare(totalReturn)}`}
            </div>
            <div className="mt-1.5 text-ds-xs text-ink-muted">
              {totalReturnPct == null ? "" : (
                <span className={totalReturnPct >= 0 ? "text-bull" : "text-bear"}>
                  {totalReturnPct >= 0 ? "+" : ""}{totalReturnPct.toFixed(2)}%
                </span>
              )}{" "}equity − deposit · every trade ever ("Today" = today only)
            </div>
          </div>
        </div>

        {/* ── Supporting row: now / today / risk / market ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Open P&L · now"
              value={
                combined.openPnl == null
                  ? "—"
                  : `${combined.openPnl >= 0 ? "+" : "−"}${fmtMoneyBare(combined.openPnl)}`
              }
              unit="USD"
              tone={openPnlTone === "neutral" ? "neutral" : openPnlTone}
              animateOn={combined.openPnl}
              sub={
                totalUnrealR == null ? (
                  "floating"
                ) : (
                  <span className={colorForR(totalUnrealR)}>
                    {totalUnrealR >= 0 ? "+" : ""}{totalUnrealR.toFixed(2)}R floating
                  </span>
                )
              }
            />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Today"
              value={
                dayPnl == null ? "—" : `${dayPnl >= 0 ? "+" : "−"}${fmtMoneyBare(dayPnl)}`
              }
              unit="USD"
              tone={dayPnl == null ? "neutral" : dayPnl >= 0 ? "bull" : "bear"}
              animateOn={dayPnl}
              sub="closed + booked + float"
            />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile
              label="Open Risk"
              value={riskUsd > 0 ? fmtMoneyBare(riskUsd) : "0"}
              unit="USD"
              sub={`${combined.positions} pos · ${nLong}L ${nShort}S`}
              tone={combined.positions > 0 ? "neutral" : "neutral"}
            />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile
              label="XAU / USD"
              value={<PriceValue value={px} digits={2} />}
              sub={
                feedAge < 0
                  ? "waiting"
                  : feedAge <= 5
                  ? `live · ${strategiesLive} legs`
                  : `${feedAge}s ago`
              }
            />
          </div>
        </div>
      </section>

      {/* ══ SECTION 02 · open positions ══ */}
      <section className="flex flex-col gap-3">
        <SectionHeader
          index="02"
          title="Open Positions"
          question={
            combined.positions > 0
              ? "What are we holding, and how is it doing?"
              : "Are we in the market right now?"
          }
          right={
            combined.positions > 0 ? (
              <span className="font-mono text-ds-xs text-ink-muted">
                {combined.positions} open
              </span>
            ) : undefined
          }
        />
        {combined.positions === 0 ? (
          <div className="glass rounded-ds-lg">
            <EmptyState
              icon="⌖"
              title="No open positions"
              body="Flat right now. The gate heartbeat below confirms the system is still evaluating the market."
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            {legList
              .flatMap((l) => l.trades.map((t) => ({ t, symbol: l.run.symbol })))
              .sort((a, b) => b.t.side - a.t.side) // longs first
              .map(({ t, symbol }) => {
                const cur = prices[symbol] ?? null;
                const u = unrealFor(t, symbol);
                const lp = t.broker_ticket ? livePos[t.broker_ticket] : undefined;
                // Prefer broker-truth live $; else per-trade price math.
                const liveUsd = lp?.unrealized_usd ?? unrealUsdFor(t, symbol);
                const liveLots = lp?.volume ?? null;
                const stateCls =
                  u == null
                    ? "border-l-2 border-l-line-base"
                    : u > 0
                    ? "border-l-2 border-l-bull"
                    : u < 0
                    ? "border-l-2 border-l-bear"
                    : "border-l-2 border-l-line-base";
                return (
                  <div key={t.trade_id} className={`rounded-ds overflow-hidden ${stateCls}`}>
                    <PositionCard
                      trade={t}
                      currentPrice={cur}
                      unrealR={u}
                      liveUsd={liveUsd}
                      liveLots={liveLots}
                      bookedUsd={lp?.booked_usd ?? null}
                      now={now}
                      onClick={() => nav(`/journal?trade=${t.trade_id}`)}
                    />
                  </div>
                );
              })}
          </div>
        )}
      </section>
    </div>
  );
}

// Compact feed-status chip for the section header.
function FeedBadge({ status, age }: { status: WsStatus; age: number }) {
  const dead = status !== "open" || (age >= 0 && age > STALE_SECS);
  const stale = status === "open" && age >= 0 && age > STALE_SECS;
  const tone: "bull" | "bear" | "warn" = dead ? "bear" : stale ? "warn" : "bull";
  const label = status !== "open" ? status.toUpperCase() : stale ? "STALE" : "LIVE";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`w-1.5 h-1.5 rounded-full ds-dot ${
          tone === "bull" ? "bg-bull text-bull" : tone === "warn" ? "bg-warn text-warn" : "bg-bear text-bear"
        }`}
      />
      <Pill tone={tone} glow={tone === "bull"}>{label}</Pill>
      <span className="font-mono text-ds-xs text-ink-muted">
        {age < 0 ? "—" : `+${age}s`}
      </span>
    </span>
  );
}

// "$10,551.77" → "10,551.77" (unit shown separately by the tile).
function fmtMoneyBare(v: number | null): string {
  if (v == null || Number.isNaN(v)) return "—";
  return Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
            Equity
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
            label="Live"
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

// Human label for a leg → clean strategy name (Long / Short / …), no jargon.
function legLabel(l: LegState): string {
  return legName(l.run.strategy_id);
}

function shortLeg(l: LegState): string {
  return legName(l.run.strategy_id);
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
