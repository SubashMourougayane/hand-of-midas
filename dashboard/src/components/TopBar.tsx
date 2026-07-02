import { Link, useLocation } from "react-router-dom";
import { PanelLeft } from "lucide-react";
import { Run } from "../lib/api";
import { SpireMark } from "./SpireMark";
import { legInfo } from "../lib/labels";

export function TopBar({
  runs,
  selectedRunId,
  onSelectRun,
  onToggleSidebar,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun?: (id: string) => void;
  onToggleSidebar?: () => void;
}) {
  const loc = useLocation();
  const selectedRun = runs.find((r) => r.run_id === selectedRunId);
  const onBacktest = loc.pathname.startsWith("/backtest");
  const liveRunning = runs.filter((r) => r.mode === "live" && !r.end_ts);
  const liveRunningCount = liveRunning.length;

  return (
    <header className="h-[60px] shrink-0 flex items-center gap-3 px-4 sm:px-6 border-b border-glass-border bg-glass-subtle backdrop-blur-xl">
      {/* Sidebar toggle (desktop) */}
      {onToggleSidebar && (
        <button
          onClick={onToggleSidebar}
          aria-label="Toggle sidebar"
          className="hidden md:inline-flex items-center justify-center w-8 h-8 rounded-ds-sm text-ink-muted hover:text-ink-primary hover:bg-glass transition-colors"
        >
          <PanelLeft size={17} />
        </button>
      )}
      {/* Brand → home (landing) */}
      <Link to="/" className="flex items-center gap-3 group">
        <SpireMark
          size={22}
          bodyColor="#f5f6f7"
          ariaLabel="Hand of Midas"
          className="transition-transform duration-500 group-hover:rotate-[10deg]"
        />
        <span className="display text-[17px] leading-none text-ink-primary tracking-[0.08em] hidden sm:inline">
          HAND OF MIDAS
        </span>
        <span className="hidden md:inline text-[11px] uppercase tracking-[1.4px] text-ink-muted pl-2 border-l border-glass-border ml-1">
          Trading Terminal
        </span>
      </Link>

      <div className="flex-1" />

      {/* Live leg tabs — one per running live run (fib_v2_intraday_a, _d, ...).
          Auto-shown when 1+ live procs running AND we're not on backtest page. */}
      {/* Leg switcher only on Backtest (Live shows all positions together). */}
      {onBacktest && liveRunningCount > 0 && onSelectRun && (
        <div className="flex items-center gap-1 glass rounded-ds p-1 mr-3">
          {liveRunning.map((r) => {
            const active = r.run_id === selectedRunId;
            const info = legInfo(r.strategy_id);
            const activeCls = active
              ? "glass-strong text-ink-primary"
              : "text-ink-muted hover:text-ink-secondary";
            return (
              <button
                key={r.run_id}
                onClick={() => onSelectRun(r.run_id)}
                className={`px-3 py-1.5 rounded-ds-sm ${activeCls} flex items-center gap-2 transition-colors duration-ds`}
                title={info.name}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    info.side === "long" ? "bg-bull" : info.side === "short" ? "bg-bear" : "bg-ink-muted"
                  }`}
                />
                <span className="text-ds-sm font-semibold">{info.name}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-3">
        {/* Status indicator — reflects SYSTEM state, not the current page.
            Backtest page shows its own mode; everywhere else the badge tells
            you whether the live engine is actually running (procs alive), so
            Journal/Trades/Signals no longer falsely read "Idle" while A/D trade. */}
        {onBacktest ? (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px] text-warn">
            <span className="w-1.5 h-1.5 rounded-full bg-warn" />
            <span>Backtest</span>
          </span>
        ) : liveRunningCount > 0 ? (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px]">
            <span className="w-1.5 h-1.5 rounded-full bg-bull ds-dot text-bull" />
            <span className="text-bull neon-text-soft">Live</span>
            <span className="text-ink-muted normal-case tracking-normal font-mono text-[11px] ml-1">
              {selectedRun?.symbol ?? liveRunning[0]?.symbol ?? ""}
            </span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px] text-ink-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-ink-muted" />
            <span>Idle</span>
          </span>
        )}
      </div>
    </header>
  );
}


