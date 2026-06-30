import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Trade, SignalRow, FunnelBucket, AccountSnap } from "../lib/api";
import { WsEnvelope } from "../lib/ws";
import { Pane } from "../components/Pane";
import { DataGrid } from "../components/DataGrid";
import {
  colorForGateStatus,
  colorForR,
  fmtPrice,
  fmtR,
  fmtTime,
  fmtTs,
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
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [funnel, setFunnel] = useState<FunnelBucket[]>([]);
  const [account, setAccount] = useState<AccountSnap | null>(null);
  const nav = useNavigate();

  const refresh = async () => {
    if (!runId) return;
    try {
      const [tr, sigs, fn, acc] = await Promise.all([
        api.runTrades(runId, "open"),
        api.signalsRecent({ run_id: runId, limit: 60 }),
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

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
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
            ...prev.slice(0, 59),
          ];
        });
        // funnel can lag; refresh next tick.
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
        // Just trigger a refresh on trade transitions.
        refresh();
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

  const maxBucket = funnel.reduce((m, b) => Math.max(m, b.count), 0) || 1;

  return (
    <div className="h-full grid grid-cols-12 grid-rows-2 gap-1">
      <Pane title="Open Positions" className="col-span-5 row-span-1">
        <DataGrid<Trade>
          rows={openTrades}
          onRowClick={(t) => nav(`/journal?trade=${t.trade_id}`)}
          columns={[
            { header: "Side", cell: (t) => (
              <span className={t.side > 0 ? "text-term-green" : "text-term-red"}>
                {t.direction.toUpperCase()}
              </span>
            )},
            { header: "Entry", cell: (t) => fmtPrice(t.entry_price), align: "right" },
            { header: "Stop", cell: (t) => fmtPrice(t.stop_price), align: "right" },
            { header: "TP", cell: (t) => fmtPrice(t.take_profit_price), align: "right" },
            { header: "Risk", cell: (t) => fmtPrice(t.risk_units), align: "right" },
            { header: "Leg", cell: (t) => t.leg ?? "—" },
            { header: "Entry TS", cell: (t) => fmtTime(t.entry_timestamp) },
          ]}
        />
      </Pane>

      <Pane title="Latest Signals & Gates" className="col-span-7 row-span-1">
        <DataGrid<SignalRow>
          rows={signals}
          columns={[
            { header: "Time", cell: (s) => fmtTime(s.ts), width: "12%" },
            {
              header: "Status",
              cell: (s) => (
                <span className={colorForGateStatus(s.status)}>{s.status}</span>
              ),
              width: "38%",
            },
            { header: "Reason", cell: (s) => s.reason ?? "—", width: "30%" },
            { header: "Zone", cell: (s) => s.zone_id ?? "—", align: "right" },
          ]}
        />
      </Pane>

      <Pane title="Gate Funnel" className="col-span-5 row-span-1">
        <div className="p-2 text-term-sm space-y-0.5">
          {funnel.length === 0 && (
            <div className="text-term-textMuted">no signals yet</div>
          )}
          {funnel.map((b) => {
            const width = Math.max(2, Math.round((b.count / maxBucket) * 100));
            const cls = colorForGateStatus(b.status);
            return (
              <div key={b.status} className="flex items-center gap-2">
                <span className={`${cls} w-64 truncate`}>{b.status}</span>
                <span className="text-term-textPrimary w-12 text-right">
                  {b.count}
                </span>
                <div className="flex-1 h-3 bg-term-panel">
                  <div
                    className="h-3"
                    style={{
                      width: `${width}%`,
                      background:
                        b.status === "GATE_SIGNAL_PASSED"
                          ? "#00CC00"
                          : b.status.startsWith("GATE_PIVOT")
                          ? "#00CCFF"
                          : b.status.startsWith("GATE_SETUP_BUILT")
                          ? "#00CCFF"
                          : b.status.startsWith("GATE_")
                          ? "#FF3333"
                          : "#FF9933",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </Pane>

      <Pane title="Account · Scan Status" className="col-span-7 row-span-1">
        <div className="p-2 text-term-sm space-y-2">
          {account ? (
            <div className="grid grid-cols-4 gap-2">
              <Stat label="EQUITY" value={`$${(account.equity ?? 0).toFixed(2)}`} highlight />
              <Stat label="BALANCE" value={`$${(account.balance ?? 0).toFixed(2)}`} />
              <Stat label="OPEN P/L" value={fmtR(account.open_pnl)} valueClass={colorForR(account.open_pnl)} />
              <Stat label="POSITIONS" value={String(account.open_position ?? 0)} />
            </div>
          ) : (
            <div className="text-term-textMuted">no account snapshot yet</div>
          )}
          <div className="border-t border-term-amberDim pt-2">
            <div className="text-term-amber uppercase text-term-xs mb-1">Scan</div>
            <div className="text-term-textSecondary">
              Last account ts: {account ? fmtTs(account.ts) : "—"}
            </div>
            <div className="text-term-textSecondary">
              Signals received (this run): {signals.length}
            </div>
          </div>
        </div>
      </Pane>
    </div>
  );
}

function Stat({
  label,
  value,
  highlight,
  valueClass,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  valueClass?: string;
}) {
  return (
    <div className="border border-term-amberDim p-1">
      <div className="text-term-amber text-term-xs uppercase">{label}</div>
      <div
        className={
          valueClass ?? (highlight ? "text-term-green text-term-lg" : "text-term-textPrimary text-term-lg")
        }
      >
        {value}
      </div>
    </div>
  );
}
