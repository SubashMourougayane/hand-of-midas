import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, Run } from "./lib/api";
import { useWsLive } from "./lib/ws";
import { TopBar } from "./components/TopBar";
import { StatusBar } from "./components/StatusBar";
import { LivePage } from "./pages/LivePage";
import { JournalPage } from "./pages/JournalPage";
import { TradesPage } from "./pages/TradesPage";
import { SignalsPage } from "./pages/SignalsPage";

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [equity, setEquity] = useState<number | null>(null);
  const ws = useWsLive(selectedRunId);

  // Load runs once + every 10s.
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const rs = await api.runs(50);
        if (!mounted) return;
        setRuns(rs);
        if (!selectedRunId && rs.length > 0) {
          // Prefer the most recent LIVE run.
          const live = rs.find((r) => r.mode === "live" && !r.end_ts) ?? rs[0];
          setSelectedRunId(live.run_id);
        }
      } catch {
        /* ignore */
      }
    };
    load();
    const t = setInterval(load, 10000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, [selectedRunId]);

  // Pull latest equity for status bar.
  useEffect(() => {
    if (!selectedRunId) return;
    let mounted = true;
    const load = async () => {
      try {
        const { items } = await api.accountLatest(selectedRunId);
        if (!mounted) return;
        setEquity(items[0]?.equity ?? null);
      } catch {
        setEquity(null);
      }
    };
    load();
    const t = setInterval(load, 5000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, [selectedRunId]);

  // React to account ws pushes for instant equity refresh.
  useEffect(() => {
    return ws.onMessage((env) => {
      if (env.channel === "account" && env.run_id === selectedRunId) {
        const eq = env.payload?.equity;
        if (typeof eq === "number") setEquity(eq);
      }
    });
  }, [ws, selectedRunId]);

  const selected = runs.find((r) => r.run_id === selectedRunId) ?? null;

  return (
    <div className="h-full w-full flex flex-col bg-term-bg text-term-textPrimary">
      <TopBar runs={runs} selectedRunId={selectedRunId} onSelectRun={setSelectedRunId} />
      <div className="flex-1 min-h-0 p-1">
        <Routes>
          <Route path="/" element={<Navigate to="/live" replace />} />
          <Route
            path="/live"
            element={<LivePage runId={selectedRunId} ws={ws} />}
          />
          <Route
            path="/journal"
            element={<JournalPage runId={selectedRunId} />}
          />
          <Route
            path="/trades"
            element={<TradesPage runId={selectedRunId} />}
          />
          <Route
            path="/signals"
            element={<SignalsPage runId={selectedRunId} ws={ws} />}
          />
        </Routes>
      </div>
      <StatusBar
        status={ws.status}
        lastMessageAt={ws.lastMessageAt}
        runRef={selected?.run_ref}
        equity={equity}
      />
    </div>
  );
}
