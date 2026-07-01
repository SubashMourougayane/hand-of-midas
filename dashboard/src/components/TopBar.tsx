import { Link, useLocation } from "react-router-dom";
import { Run } from "../lib/api";
import { SpireMark } from "./SpireMark";

export function TopBar({
  runs,
  selectedRunId,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun?: (id: string) => void;
}) {
  const loc = useLocation();
  const selectedRun = runs.find((r) => r.run_id === selectedRunId);
  const onLive = loc.pathname.startsWith("/live");
  const onBacktest = loc.pathname.startsWith("/backtest");
  const liveRunningCount = runs.filter((r) => r.mode === "live" && !r.end_ts).length;

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
