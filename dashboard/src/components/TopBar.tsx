import { Link, useLocation } from "react-router-dom";
import { Run } from "../lib/api";
import { SpireMark } from "./SpireMark";

export function TopBar({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun?: (id: string) => void;
}) {
  const loc = useLocation();
  const selectedRun = runs.find((r) => r.run_id === selectedRunId);
  const onLive = loc.pathname.startsWith("/live");
  const onBacktest = loc.pathname.startsWith("/backtest");
  const liveRunning = runs.filter((r) => r.mode === "live" && !r.end_ts);
  const liveRunningCount = liveRunning.length;

  return (
    <header className="h-[60px] shrink-0 flex items-center gap-4 px-6 border-b border-line-subtle bg-bg-base/95 backdrop-blur-md">
      {/* Brand */}
      <Link to="/live" className="flex items-center gap-3 group">
        <SpireMark
          size={22}
          ariaLabel="Hand of Midas"
          className="transition-transform duration-500 group-hover:rotate-[10deg]"
        />
        <span className="display text-[19px] leading-none text-ink-primary tracking-tight hidden sm:inline">
          Hand of Midas
        </span>
        <span className="hidden md:inline text-[11px] uppercase tracking-[1.4px] text-ink-muted pl-2 border-l border-line-subtle ml-1">
          Trading Terminal
        </span>
      </Link>

      <div className="flex-1" />

      {/* Live leg tabs — one per running live run (fib_v2_intraday_a, _d, ...).
          Auto-shown when 1+ live procs running AND we're not on backtest page. */}
      {!onBacktest && liveRunningCount > 0 && onSelectRun && (
        <div className="flex items-center gap-1 bg-bg-elevated border border-line-base rounded-ds p-1 mr-3">
          {liveRunning.map((r) => {
            const active = r.run_id === selectedRunId;
            const label = _legLabel(r.strategy_id);
            const tone = _legTone(r.strategy_id);
            const activeCls = active
              ? tone === "bull"
                ? "bg-bull/15 text-bull border-bull/40"
                : tone === "bear"
                  ? "bg-bear/15 text-bear border-bear/40"
                  : "bg-info/15 text-info border-info/40"
              : "text-ink-muted hover:text-ink-secondary border-transparent";
            return (
              <button
                key={r.run_id}
                onClick={() => onSelectRun(r.run_id)}
                className={`px-3 py-1.5 rounded-ds-sm border ${activeCls} flex items-center gap-2 transition-colors duration-ds`}
                title={r.run_ref || r.run_id}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${active ? "bg-current" : "bg-ink-muted"}`} />
                <span className="text-ds-sm font-semibold">{label}</span>
                <span className="text-ds-xs font-mono opacity-60">
                  {r.run_id.slice(0, 6)}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-3">
        {/* Status indicator — driven by current PAGE.
            Backtest pages have their own run picker; live shows the active one. */}
        {onBacktest ? (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px] text-warn">
            <span className="w-1.5 h-1.5 rounded-full bg-warn" />
            <span>Backtest</span>
          </span>
        ) : onLive && liveRunningCount > 0 && selectedRun?.mode === "live" ? (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px]">
            <span className="w-1.5 h-1.5 rounded-full bg-bull ds-dot text-bull" />
            <span className="text-bull">Live</span>
            {selectedRun && (
              <span className="text-ink-muted normal-case tracking-normal font-mono text-[11px] ml-1">
                {selectedRun.symbol}
              </span>
            )}
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


function _legLabel(strategyId: string): string {
  if (strategyId.endsWith("_a") || strategyId.includes("_a_")) return "A · LONG";
  if (strategyId.endsWith("_d") || strategyId.includes("_d_")) return "D · SHORT";
  if (strategyId.includes("a_plus_d")) return "A+D";
  return strategyId.toUpperCase();
}


function _legTone(strategyId: string): "bull" | "bear" | "info" {
  if (strategyId.endsWith("_a") || strategyId.includes("_a_")) return "bull";
  if (strategyId.endsWith("_d") || strategyId.includes("_d_")) return "bear";
  return "info";
}
