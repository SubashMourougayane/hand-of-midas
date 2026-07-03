import { useEffect, useMemo, useState } from "react";
import { api, AccountSnap, FunnelBucket, SignalRow as SignalRowT } from "../lib/api";
import { WsEnvelope } from "../lib/ws";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { Funnel } from "../components/Funnel";
import { SignalRowItem } from "../components/SignalRow";
import { SectionHeader } from "../components/ui/Section";
import { StatTile } from "../components/ui/StatTile";

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
  const [bars, setBars] = useState<AccountSnap[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [legFilter, setLegFilter] = useState<string>("");
  const [newIds, setNewIds] = useState<Set<number>>(new Set());

  const refresh = async () => {
    if (!runId) return;
    // Resolve which runs to include. For a LIVE run, merge signals across the
    // recent runs of the SAME strategy so a restart (which forks a new run_id)
    // doesn't visually reset the funnel / feed. BT run → just itself.
    let runIds: string[] = [runId];
    let selfRun: any = null;
    try {
      const d: any = await api.runDetail(runId);
      selfRun = d?.run ?? null;
    } catch {
      /* ignore */
    }
    if (selfRun?.mode === "live" && selfRun?.strategy_id) {
      try {
        const all = await api.runs(100, "live");
        const sibs = all
          .filter((r: any) => r.strategy_id === selfRun.strategy_id)
          .sort((a: any, b: any) => (b.start_ts || "").localeCompare(a.start_ts || ""))
          .slice(0, 4) // current + a few recent restarts
          .map((r: any) => r.run_id);
        if (sibs.length) runIds = Array.from(new Set([runId, ...sibs]));
      } catch {
        /* fall back to single run */
      }
    }

    const sigLists = await Promise.all(
      runIds.map((rid) =>
        api
          .signalsRecent({
            run_id: rid,
            limit: 500,
            status_prefix: statusFilter || undefined,
            leg: legFilter || undefined,
          })
          .catch(() => [] as SignalRowT[])
      )
    );
    const fnLists = await Promise.all(
      runIds.map((rid) => api.funnel(rid).then((f) => f.buckets).catch(() => [] as FunnelBucket[]))
    );
    const barSeries = await api.accountSeries(runId, 500).catch(() => [] as AccountSnap[]);

    // Merge + sort signals newest-first, cap 500.
    const mergedSigs = sigLists
      .flat()
      .sort((a, b) => (b.ts || "").localeCompare(a.ts || ""))
      .slice(0, 500);
    // Sum funnel counts per status across runs.
    const fnMap = new Map<string, number>();
    for (const b of fnLists.flat()) {
      fnMap.set(b.status, (fnMap.get(b.status) ?? 0) + b.count);
    }
    setSignals(mergedSigs);
    setFunnel(Array.from(fnMap, ([status, count]) => ({ status, count })));
    setBars(barSeries);
  };

  // Initial load only — WS pushes drive subsequent updates.
  useEffect(() => {
    refresh();
  }, [runId, statusFilter, legFilter]);

  // Bar heartbeat: append account snapshots as they arrive.
  useEffect(() => {
    return ws.onMessage((env) => {
      if (env.run_id !== runId) return;
      if (env.channel !== "account") return;
      const p = env.payload as any;
      setBars((prev) => {
        // Dedup on ts.
        if (prev.some((b) => b.ts === p.ts)) return prev;
        return [
          ...prev,
          {
            snap_id: p.snap_id ?? 0,
            ts: p.ts,
            balance: p.balance ?? null,
            equity: p.equity ?? null,
            open_pnl: p.open_pnl ?? null,
            open_position: p.open_position ?? null,
          },
        ].slice(-500);
      });
    });
  }, [ws, runId]);

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

  // Merge signals + bar heartbeats into ONE timeline, sorted desc by ts.
  // Heartbeats appear as low-contrast rows so silent bars (no gate fired)
  // still show a pulse — user sees the run is alive even between events.
  const timeline = useMemo(() => {
    type Item =
      | { kind: "signal"; ts: string; key: string; sig: SignalRowT }
      | { kind: "bar"; ts: string; key: string; bar: AccountSnap };
    const items: Item[] = [];
    for (const s of signals) {
      items.push({ kind: "signal", ts: s.ts, key: `s${s.signal_id}`, sig: s });
    }
    for (const b of bars) {
      // Skip bar if a signal already shows at the same ts — the signal row
      // is already visible for that bar close, redundant heartbeat clutters.
      const same_ts = signals.some((s) => s.ts === b.ts);
      if (same_ts) continue;
      items.push({ kind: "bar", ts: b.ts, key: `b${b.snap_id}-${b.ts}`, bar: b });
    }
    return items.sort((a, b) => b.ts.localeCompare(a.ts));
  }, [signals, bars]);
  const lastBar = bars.length ? bars[bars.length - 1] : null;

  return (
    <div className="h-full overflow-auto flex flex-col gap-6 px-4 sm:px-6 py-5 min-h-0 w-full">
      {/* ══ SECTION 01 · gate performance ══ */}
      <section className="flex flex-col gap-3 shrink-0">
        <SectionHeader index="01" title="Decision Funnel" question="How does the system evaluate the market?" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
          <div className="glass rounded-ds-lg">
            <StatTile label="Total Gates" value={total.toLocaleString()} />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile label="Passed" value={passCount.toLocaleString()} tone="bull" />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile label="Rejected" value={rejectCount.toLocaleString()} tone="bear" />
          </div>
          <div className="glass rounded-ds-lg">
            <StatTile label="Pass Rate" value={total ? ((passCount / total) * 100).toFixed(1) : "—"} unit="%" />
          </div>
        </div>
      </section>

      {/* Stream (full width on mobile, 8/12 on desktop) + Funnel side panel */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-3 min-h-0">
        <Pane
          title="Signal Stream"
          subtitle={
            lastBar
              ? `${signals.length} signals · ${bars.length} bars · last bar ${new Date(lastBar.ts).toISOString().slice(11, 16)}Z`
              : `${signals.length} signals loaded`
          }
          toolbar={
            <div className="flex flex-wrap items-center gap-2 w-full">
              <input
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                placeholder="filter by status prefix…"
                className="
                  bg-bg-input border border-line-base rounded-ds-sm
                  px-2 py-1 text-ds-sm font-mono text-ink-primary
                  placeholder:text-ink-muted
                  focus:outline-none focus:border-brass
                  flex-1 min-w-[140px] max-w-xs
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
                  focus:outline-none focus:border-brass
                  flex-1 min-w-[100px] max-w-[12rem]
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
          className="lg:col-span-8 min-h-[50vh] lg:min-h-0 overflow-auto"
        >
          {timeline.length === 0 ? (
            <div className="px-3 py-10 text-center text-ink-muted text-ds-sm">
              No signals or bars yet
            </div>
          ) : (
            <div>
              {timeline.map((it) =>
                it.kind === "signal" ? (
                  <SignalRowItem
                    key={it.key}
                    signal={it.sig}
                    isNew={newIds.has(it.sig.signal_id)}
                    expandable
                  />
                ) : (
                  <BarHeartbeatRow key={it.key} bar={it.bar} />
                )
              )}
            </div>
          )}
        </Pane>

        <Pane
          title="Gate Funnel"
          subtitle="lifetime"
          className="lg:col-span-4 min-h-[30vh] lg:min-h-0 overflow-auto"
        >
          <Funnel buckets={funnel} total={total} />
        </Pane>
      </div>
    </div>
  );
}


function BarHeartbeatRow({ bar }: { bar: AccountSnap }) {
  const t = new Date(bar.ts);
  const hhmm = t.toISOString().slice(11, 16);
  return (
    <div className="border-b border-line-subtle px-3 py-1.5 flex items-center gap-3 text-ds-xs opacity-60 hover:opacity-100 transition-opacity">
      <span className="w-1.5 h-1.5 rounded-full bg-ink-muted" />
      <span className="font-mono text-ink-muted">{hhmm}Z</span>
      <span className="text-ink-muted uppercase tracking-wide">BAR</span>
      <span className="text-ink-secondary">bar closed — strategy silent (no active setup)</span>
      <span className="ml-auto font-mono text-ink-muted">
        {bar.equity !== null ? `eq $${bar.equity.toFixed(2)}` : ""}
        {bar.open_position !== null ? ` · pos ${bar.open_position}` : ""}
      </span>
    </div>
  );
}
