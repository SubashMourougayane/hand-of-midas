import { useEffect, useMemo, useState } from "react";
import { api, FunnelBucket, SignalRow as SignalRowT } from "../lib/api";
import { WsEnvelope } from "../lib/ws";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { Funnel } from "../components/Funnel";
import { SignalRowItem } from "../components/SignalRow";
import { KPI } from "../components/KPI";

type WsHook = {
  onMessage: (fn: (env: WsEnvelope) => void) => () => void;
};

export function SignalsPage({
  runId,
  ws,
}: {
  runId: string | null;
  ws: WsHook;
}) {
  const [signals, setSignals] = useState<SignalRowT[]>([]);
  const [funnel, setFunnel] = useState<FunnelBucket[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [legFilter, setLegFilter] = useState<string>("");
  const [newIds, setNewIds] = useState<Set<number>>(new Set());

  const refresh = async () => {
    if (!runId) return;
    const [sigs, fn] = await Promise.all([
      api.signalsRecent({
        run_id: runId,
        limit: 500,
        status_prefix: statusFilter || undefined,
        leg: legFilter || undefined,
      }),
      api.funnel(runId),
    ]);
    setSignals(sigs);
    setFunnel(fn.buckets);
  };

  // Initial load only — WS pushes drive subsequent updates.
  useEffect(() => {
    refresh();
  }, [runId, statusFilter, legFilter]);

  useEffect(() => {
    return ws.onMessage((env) => {
      if (env.run_id !== runId) return;
      if (env.channel !== "signal") return;
      const sig = env.payload as any;
      if (statusFilter && !String(sig.status).startsWith(statusFilter)) return;
      setSignals((prev) => [
        {
          signal_id: sig.signal_id,
          run_id: sig.run_id,
          ts: sig.ts,
          status: sig.status,
          reason: sig.reason ?? null,
          zone_id: sig.zone_id ?? null,
          detail: null,
        },
        ...prev.slice(0, 499),
      ]);
      setNewIds((prev) => new Set(prev).add(sig.signal_id));
      setTimeout(() => {
        setNewIds((prev) => {
          const next = new Set(prev);
          next.delete(sig.signal_id);
          return next;
        });
      }, 800);
      setFunnel((prev) => {
        const exists = prev.find((b) => b.status === sig.status);
        if (exists)
          return prev.map((b) =>
            b.status === sig.status ? { ...b, count: b.count + 1 } : b
          );
        return [...prev, { status: sig.status, count: 1 }];
      });
    });
  }, [ws, runId, statusFilter]);

  const passCount = useMemo(
    () => funnel.find((b) => b.status === "GATE_SIGNAL_PASSED")?.count ?? 0,
    [funnel]
  );
  const total = useMemo(() => funnel.reduce((s, b) => s + b.count, 0), [funnel]);
  const rejectCount = total - passCount;

  return (
    <div className="h-full flex flex-col gap-3 p-3 min-h-0">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 shrink-0">
        <KPI label="Total Gates" value={total.toLocaleString()} />
        <KPI label="Passed" value={passCount.toLocaleString()} deltaTone="bull" />
        <KPI label="Rejected" value={rejectCount.toLocaleString()} deltaTone="bear" />
        <KPI
          label="Pass Rate"
          value={total ? `${((passCount / total) * 100).toFixed(2)}%` : "—"}
        />
      </div>

      <div className="flex-1 grid grid-cols-12 gap-3 min-h-0">
        <Pane
          title="Signal Stream"
          subtitle={`${signals.length} loaded`}
          toolbar={
            <div className="flex items-center gap-2">
              <input
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                placeholder="filter by status prefix…"
                className="
                  bg-bg-input border border-line-base rounded-ds-sm
                  px-2 py-1 text-ds-sm font-mono text-ink-primary
                  placeholder:text-ink-muted
                  focus:outline-none focus:border-bull
                  w-72
                "
              />
              <input
                value={legFilter}
                onChange={(e) => setLegFilter(e.target.value)}
                placeholder="filter by leg…"
                className="
                  bg-bg-input border border-line-base rounded-ds-sm
                  px-2 py-1 text-ds-sm font-mono text-ink-primary
                  placeholder:text-ink-muted
                  focus:outline-none focus:border-bull
                  w-48
                "
              />
              {(statusFilter || legFilter) && (
                <button
                  onClick={() => {
                    setStatusFilter("");
                    setLegFilter("");
                  }}
                  className="text-ds-xs text-ink-muted hover:text-ink-primary"
                >
                  clear
                </button>
              )}
              <span className="ml-auto text-ds-xs text-ink-muted">
                <Pill tone="bull">{passCount} pass</Pill>
              </span>
            </div>
          }
          className="col-span-12 lg:col-span-8 min-h-0"
        >
          {signals.length === 0 ? (
            <div className="px-3 py-10 text-center text-ink-muted text-ds-sm">
              No signals match filter
            </div>
          ) : (
            <div>
              {signals.map((s) => (
                <SignalRowItem
                  key={s.signal_id}
                  signal={s}
                  isNew={newIds.has(s.signal_id)}
                  expandable
                />
              ))}
            </div>
          )}
        </Pane>

        <Pane
          title="Gate Funnel"
          subtitle="lifetime"
          className="col-span-12 lg:col-span-4 min-h-0"
        >
          <Funnel buckets={funnel} total={total} />
        </Pane>
      </div>
    </div>
  );
}
