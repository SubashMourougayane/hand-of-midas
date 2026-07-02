import { useEffect, useMemo, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AccountSnap, api, Run } from "./lib/api";
import { useWsLive } from "./lib/ws";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { MobileNav } from "./components/MobileNav";
import { StatusBar } from "./components/StatusBar";
import { LandingPage } from "./pages/LandingPage";
import { LivePage } from "./pages/LivePage";
import { JournalPage } from "./pages/JournalPage";
import { TradesPage } from "./pages/TradesPage";
import { SignalsPage } from "./pages/SignalsPage";
import { BacktestPage } from "./pages/BacktestPage";
import { ArchitecturePage } from "./pages/ArchitecturePage";

export default function AppRoot() {
  return (
    <Routes>
      {/* Full-bleed landing — no app shell. */}
      <Route path="/" element={<LandingPage />} />
      {/* Everything else runs inside the terminal shell. */}
      <Route path="*" element={<App />} />
    </Routes>
  );
}

function App() {
  const loc = useLocation();
  const [allRuns, setAllRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountSnap | null>(null);
  const [signalsSeen, setSignalsSeen] = useState(0);
  // Collapsible sidebar — persisted so it survives reloads.
  const [collapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem("hom.sidebar.collapsed") === "1"
  );
  const toggleSidebar = () =>
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem("hom.sidebar.collapsed", next ? "1" : "0");
      return next;
    });
  const ws = useWsLive(selectedRunId);
  const onBacktest = loc.pathname.startsWith("/backtest");
  // Each page wants its own slice — Backtest sees bt runs; everything else sees live.
  const runs = useMemo(
    () => allRuns.filter((r) => (onBacktest ? r.mode === "bt" : r.mode === "live")),
    [allRuns, onBacktest]
  );

  // Load all runs initially + every 60s as fallback. Runs aren't part of the
  // WS feed (only trade/signal/journal/account channels are), so a slow poll
  // is the only way to detect a freshly-created run from another process.
  // Live trade/signal/account data all arrives via WS — this is discovery-only.
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const rs = await api.runs(100);
        if (!mounted) return;
        setAllRuns(rs);
      } catch {
        /* ignore */
      }
    };
    load();
    const t = setInterval(load, 60000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, []);

  // Auto-select a run from the current filtered set when current is missing.
  useEffect(() => {
    if (runs.length === 0) {
      setSelectedRunId(null);
      return;
    }
    const current = selectedRunId
      ? runs.find((r) => r.run_id === selectedRunId)
      : null;
    // On Live page, if current selection has ended_at, switch to a running one.
    const needsReselect =
      !current || (!onBacktest && current.mode === "live" && current.end_ts != null);
    if (needsReselect) {
      const pick = onBacktest
        ? runs[0]
        : runs.find((r) => r.mode === "live" && !r.end_ts) ?? runs[0];
      if (pick.run_id !== selectedRunId) setSelectedRunId(pick.run_id);
    }
  }, [runs, selectedRunId, onBacktest]);

  // Initial account snap fetch. After that, WS `account` channel pushes update
  // setAccount when MT5 publishes a new bar-close snapshot. NO polling.
  useEffect(() => {
    if (!selectedRunId) {
      setAccount(null);
      return;
    }
    let mounted = true;
    api
      .accountLatest(selectedRunId)
      .then(({ items }) => mounted && setAccount(items[0] ?? null))
      .catch(() => mounted && setAccount(null));
    return () => {
      mounted = false;
    };
  }, [selectedRunId]);

  // Live updates via ws.
  useEffect(() => {
    return ws.onMessage((env) => {
      // Broker-truth account (account-wide, run_id null) — matches the Live
      // cockpit's PnlHero so the bottom StatusBar shows the SAME equity/balance.
      if (env.channel === "account_live") {
        const p = env.payload as any;
        setAccount((prev) => ({
          snap_id: prev?.snap_id ?? 0,
          ts: env.ts,
          balance: typeof p.balance === "number" ? p.balance : prev?.balance ?? null,
          equity: typeof p.equity === "number" ? p.equity : prev?.equity ?? null,
          open_pnl: typeof p.open_pnl === "number" ? p.open_pnl : null,
          open_position: prev?.open_position ?? null,
        }));
        return;
      }
      if (env.run_id !== selectedRunId) return;
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
      if (env.channel === "signal") {
        setSignalsSeen((n) => n + 1);
      }
    });
  }, [ws, selectedRunId]);

  // Reset signals-seen counter on run switch.
  useEffect(() => {
    setSignalsSeen(0);
  }, [selectedRunId]);

  const selected = runs.find((r) => r.run_id === selectedRunId) ?? null;

  return (
    <div className="h-full w-full flex flex-col bg-bg-base text-ink-primary font-sans">
      <TopBar
        runs={runs}
        selectedRunId={selectedRunId}
        onSelectRun={setSelectedRunId}
        onToggleSidebar={toggleSidebar}
      />
      <div className="flex-1 min-h-0 overflow-hidden flex">
        <Sidebar collapsed={collapsed} />
        <main className="flex-1 min-w-0 overflow-hidden pb-14 md:pb-0">
          <Routes>
            <Route
              path="/live"
              element={<LivePage runId={selectedRunId} ws={ws} />}
            />
            <Route
              path="/backtest"
              element={<BacktestPage runs={runs} selectedRunId={selectedRunId} onSelectRun={setSelectedRunId} />}
            />
            <Route
              path="/journal"
              element={<JournalPage runId={selectedRunId} />}
            />
            <Route
              path="/trades"
              element={<TradesPage runId={selectedRunId} ws={ws} />}
            />
            <Route
              path="/signals"
              element={<SignalsPage runId={selectedRunId} ws={ws} />}
            />
            <Route
              path="/architecture"
              element={<ArchitecturePage />}
            />
          </Routes>
        </main>
      </div>
      <div className="hidden md:block">
        <StatusBar
          status={ws.status}
          lastMessageAt={ws.lastMessageAt}
          runRef={selected?.run_ref}
          equity={account?.equity ?? null}
          balance={account?.balance ?? null}
          openPositions={account?.open_position ?? null}
          signalsSeen={signalsSeen}
        />
      </div>
      <MobileNav />
    </div>
  );
}

function ArchitecturePlaceholder() {
  return (
    <div className="h-full flex items-center justify-center text-ink-muted text-ds-md p-6">
      Architecture view coming soon.
    </div>
  );
}
