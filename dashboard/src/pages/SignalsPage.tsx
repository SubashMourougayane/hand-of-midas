import { useEffect, useMemo, useState } from "react";
import { api, FunnelBucket, SignalRow } from "../lib/api";
import { WsEnvelope } from "../lib/ws";
import { Pane } from "../components/Pane";
import { DataGrid } from "../components/DataGrid";
import { colorForGateStatus, fmtTs } from "../lib/format";

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
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [funnel, setFunnel] = useState<FunnelBucket[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [legFilter, setLegFilter] = useState<string>("");

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

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
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

  return (
    <div className="h-full grid grid-cols-12 gap-1">
      <Pane title="Signals" className="col-span-8">
        <div className="flex gap-2 px-2 py-1 border-b border-term-amberDim text-term-xs">
          <input
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            placeholder="GATE_SIGNAL_…"
            className="bg-term-bg border border-term-amberDim px-1 py-0.5 text-term-amber w-64"
          />
          <input
            value={legFilter}
            onChange={(e) => setLegFilter(e.target.value)}
            placeholder="leg (intraday_a_long …)"
            className="bg-term-bg border border-term-amberDim px-1 py-0.5 text-term-amber w-64"
          />
          <span className="ml-auto text-term-textMuted">
            {signals.length} loaded · {passCount} passed
          </span>
        </div>
        <DataGrid<SignalRow>
          rows={signals}
          columns={[
            { header: "Time", cell: (s) => fmtTs(s.ts), width: "20%" },
            {
              header: "Status",
              cell: (s) => (
                <span className={colorForGateStatus(s.status)}>{s.status}</span>
              ),
              width: "30%",
            },
            { header: "Reason", cell: (s) => s.reason ?? "—" },
            { header: "Zone", cell: (s) => s.zone_id ?? "—", align: "right" },
          ]}
        />
      </Pane>
      <Pane title="Funnel" className="col-span-4">
        <div className="p-2 text-term-sm space-y-0.5">
          {funnel.length === 0 && <div className="text-term-textMuted">no data</div>}
          {(() => {
            const max = funnel.reduce((m, b) => Math.max(m, b.count), 0) || 1;
            return funnel
              .slice()
              .sort((a, b) => b.count - a.count)
              .map((b) => {
                const width = Math.max(2, Math.round((b.count / max) * 100));
                return (
                  <div key={b.status} className="flex items-center gap-2">
                    <span className={`${colorForGateStatus(b.status)} w-52 truncate`}>
                      {b.status}
                    </span>
                    <span className="w-10 text-right">{b.count}</span>
                    <div className="flex-1 h-3 bg-term-panel">
                      <div
                        className="h-3"
                        style={{
                          width: `${width}%`,
                          background:
                            b.status === "GATE_SIGNAL_PASSED"
                              ? "#00CC00"
                              : b.status.startsWith("GATE_PIVOT") || b.status.startsWith("GATE_SETUP_BUILT")
                              ? "#00CCFF"
                              : b.status.startsWith("GATE_")
                              ? "#FF3333"
                              : "#FF9933",
                        }}
                      />
                    </div>
                  </div>
                );
              });
          })()}
        </div>
      </Pane>
    </div>
  );
}
