import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AccountSnap,
  api,
  FunnelBucket,
  SignalRow as SignalRowT,
  Trade,
} from "../lib/api";
import { WsEnvelope } from "../lib/ws";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { PositionCard } from "../components/PositionCard";
import { KPI } from "../components/KPI";
import { LiveChart } from "../components/LiveChart";
import {
  fmtMoney,
  fmtR,
  fmtTs,
  colorForR,
} from "../lib/format";

type WsHook = {
  status: string;
  lastMessageAt: number;
  onMessage: (fn: (env: WsEnvelope) => void) => () => void;
};

export function LivePage({
  runId,
  ws,
}: {
  runId: string | null;
  ws: WsHook;
}) {
  const [openTrades, setOpenTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<SignalRowT[]>([]);
  const [funnel, setFunnel] = useState<FunnelBucket[]>([]);
  const [account, setAccount] = useState<AccountSnap | null>(null);
  const [newSignalIds, setNewSignalIds] = useState<Set<number>>(new Set());
  const nav = useNavigate();
  const flashTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const refresh = async () => {
    if (!runId) return;
    try {
      const [tr, sigs, fn, acc] = await Promise.all([
        api.runTrades(runId, "open"),
        api.signalsRecent({ run_id: runId, limit: 100 }),
        api.funnel(runId),
        api.accountLatest(runId).catch(() => ({ items: [] as AccountSnap[] })),
      ]);
      setOpenTrades(tr.items);
      setSignals(sigs);
      setFunnel(fn.buckets);
      setAccount(acc.items?.[0] ?? null);
    } catch {
      /* keep stale */
    }
  };

  // Initial-load only. After that, WebSocket pushes drive updates.
  // (No polling — Postgres NOTIFY → asyncpg LISTEN → ws fanout → setState here.)
  useEffect(() => {
    refresh();
  }, [runId]);

  useEffect(() => {
    return ws.onMessage((env) => {
      if (env.run_id !== runId) return;
      if (env.channel === "signal") {
        const sig = env.payload as any;
        setSignals((prev) => {
          if (prev[0]?.signal_id === sig.signal_id) return prev;
          return [
            {
              signal_id: sig.signal_id,
              run_id: sig.run_id,
              ts: sig.ts,
              status: sig.status,
              reason: sig.reason ?? null,
              zone_id: sig.zone_id ?? null,
              detail: null,
            },
            ...prev.slice(0, 99),
          ];
        });
        // Mark as "new" briefly for flash.
        setNewSignalIds((prev) => new Set(prev).add(sig.signal_id));
        const existing = flashTimers.current.get(sig.signal_id);
        if (existing) clearTimeout(existing);
        flashTimers.current.set(
          sig.signal_id,
          setTimeout(() => {
            setNewSignalIds((prev) => {
              const next = new Set(prev);
              next.delete(sig.signal_id);
              return next;
            });
            flashTimers.current.delete(sig.signal_id);
          }, 800)
        );
        setFunnel((prev) => {
          const exists = prev.find((b) => b.status === sig.status);
          if (exists) {
            return prev.map((b) =>
              b.status === sig.status ? { ...b, count: b.count + 1 } : b
            );
          }
          return [...prev, { status: sig.status, count: 1 }];
        });
      }
      if (env.channel === "trade") {
        // Refetch open trades only — single REST call, not the full refresh().
        api.runTrades(runId!, "open").then((tr) => setOpenTrades(tr.items));
      }
      if (env.channel === "account") {
        const p = env.payload as any;
        setAccount({
          snap_id: p.snap_id,
          ts: p.ts,
          balance: p.balance ?? null,
          equity: p.equity ?? null,
          open_pnl: null,
          open_position: p.open_position ?? null,
        });
      }
    });
  }, [ws, runId]);

  const passCount = useMemo(
    () => funnel.find((b) => b.status === "GATE_SIGNAL_PASSED")?.count ?? 0,
    [funnel]
  );
  const totalGateEvents = useMemo(
    () => funnel.reduce((s, b) => s + b.count, 0),
    [funnel]
  );
  const passRate = totalGateEvents ? (passCount / totalGateEvents) * 100 : 0;
  const totalRiskUnits = useMemo(
    () => openTrades.reduce((s, t) => s + (t.risk_units ?? 0), 0),
    [openTrades]
  );

  const pnl = account?.open_pnl ?? null;
  const pnlTone = pnl == null ? "neutral" : pnl >= 0 ? "bull" : "bear";

  return (
    <div className="h-full overflow-auto flex flex-col gap-3 p-3">
      {/* ── KPI strip ── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 shrink-0">
        <KPI
          label="Equity"
          value={fmtMoney(account?.equity)}
          delta={
            pnl != null && pnl !== 0 ? (
              <>{pnl >= 0 ? "+" : ""}{fmtMoney(pnl, 2)}</>
            ) : undefined
          }
          deltaTone={pnlTone}
          sub={account ? `as of ${fmtTs(account.ts)}` : "no snapshot yet"}
        />
        <KPI
          label="Balance"
          value={fmtMoney(account?.balance)}
          sub="settled"
        />
        <KPI
          label="Open Positions"
          value={openTrades.length}
          sub={`${totalRiskUnits.toFixed(2)} risk units`}
        />
        <KPI
          label="Pass Rate"
          value={`${passRate.toFixed(2)}%`}
          sub={`${passCount} passed / ${totalGateEvents.toLocaleString()} gates`}
          deltaTone={passCount > 0 ? "bull" : "neutral"}
        />
        <KPI
          label="Last Event"
          value={signals[0] ? fmtTs(signals[0].ts).slice(11) : "—"}
          sub={signals[0]?.status?.replace(/^GATE_/, "").toLowerCase() ?? "—"}
        />
      </div>

      {/* ── Live market chart (TradingView M15 XAUUSD) ── */}
      <Pane
        title="XAU/USD · M15"
        subtitle="OANDA feed · real-time"
        right={
          <span className="text-ds-xs text-ink-muted">
            chart by TradingView
          </span>
        }
        className="shrink-0"
      >
        <div className="h-[460px]">
          <LiveChart symbol="OANDA:XAUUSD" interval="15" />
        </div>
      </Pane>

      {/* ── Open positions only ── */}
      <Pane
        title="Open Positions"
        subtitle={openTrades.length > 0 ? `${openTrades.length} live` : ""}
        right={
          openTrades.length > 0 && (
            <Pill tone="bull" glow>
              <span className="text-bull">●</span> LIVE
            </Pill>
          )
        }
      >
        {openTrades.length === 0 ? (
          <EmptyState
            icon="⌖"
            title="No open positions"
            body="Waiting for the next valid setup. See the Signals page for the live gate funnel + decision trace."
          />
        ) : (
          <div className="p-3 space-y-3">
            {openTrades.map((t) => (
              <PositionCard
                key={t.trade_id}
                trade={t}
                unrealR={null}
                onClick={() => nav(`/journal?trade=${t.trade_id}`)}
              />
            ))}
          </div>
        )}
      </Pane>
    </div>
  );
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
