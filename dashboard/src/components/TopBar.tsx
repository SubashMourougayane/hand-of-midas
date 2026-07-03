import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { PanelLeft } from "lucide-react";
import { Run } from "../lib/api";
import { SpireMark } from "./SpireMark";
import { legInfo } from "../lib/labels";
import { fmtMoney } from "../lib/format";

const DEPOSIT_BASELINE = 10000;

export function TopBar({
  runs,
  selectedRunId,
  onSelectRun,
  onToggleSidebar,
  equity,
  balance,
  xauPrice,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun?: (id: string) => void;
  onToggleSidebar?: () => void;
  equity?: number | null;
  balance?: number | null;
  xauPrice?: number | null;
}) {
  const loc = useLocation();
  const selectedRun = runs.find((r) => r.run_id === selectedRunId);
  const onBacktest = loc.pathname.startsWith("/backtest");
  const liveRunning = runs.filter((r) => r.mode === "live" && !r.end_ts);
  const liveRunningCount = liveRunning.length;

  const totalReturn = equity != null ? equity - DEPOSIT_BASELINE : null;
  const totalReturnPct =
    totalReturn != null ? (totalReturn / DEPOSIT_BASELINE) * 100 : null;
  const tone =
    totalReturn == null ? "muted" : totalReturn >= 0 ? "bull" : "bear";

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
      {/* Brand → home (landing). Mark sits in a soft gold coin for presence. */}
      <Link to="/" className="flex items-center gap-3 group shrink-0">
        <span className="relative flex items-center justify-center w-9 h-9 rounded-ds-sm bg-gradient-to-br from-[#3a2f10] to-[#1a1608] border border-[#5a4a18]/40 shadow-[0_0_18px_-6px_rgba(212,175,55,0.5)] transition-transform duration-500 group-hover:rotate-[8deg]">
          <SpireMark size={20} bodyColor="#e8c65a" ariaLabel="Hand of Midas" />
        </span>
        <span className="flex flex-col leading-none">
          <span className="display text-[16px] text-ink-primary tracking-[0.09em] hidden sm:inline">
            HAND OF MIDAS
          </span>
          <span className="hidden sm:inline text-[9px] uppercase tracking-[2.2px] text-ink-muted mt-1">
            Trading Terminal
          </span>
        </span>
      </Link>

      {/* Live account pulse — fills the bar with the numbers that matter on
          EVERY page (not just Live). Equity · all-time return · XAU mark. */}
      <div className="flex-1 min-w-0 flex items-center justify-center">
        <div className="hidden lg:flex items-center gap-0 glass rounded-ds px-1 py-1">
          <PulseStat
            label="Equity"
            value={equity == null ? "—" : fmtMoney(equity, 2)}
            valueTone="primary"
          />
          <Divider />
          <PulseStat
            label="Return · since $10k"
            value={
              totalReturn == null
                ? "—"
                : `${totalReturn >= 0 ? "+" : "−"}${fmtMoney(Math.abs(totalReturn), 0)}`
            }
            sub={
              totalReturnPct == null
                ? undefined
                : `${totalReturnPct >= 0 ? "+" : ""}${totalReturnPct.toFixed(2)}%`
            }
            valueTone={tone}
          />
          <Divider />
          <XauTicker price={xauPrice ?? null} />
        </div>
      </div>

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

      <div className="flex items-center gap-3 shrink-0">
        {/* System-state badge — running procs, not the current page. */}
        {onBacktest ? (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px] text-warn">
            <span className="w-1.5 h-1.5 rounded-full bg-warn" />
            <span>Backtest</span>
          </span>
        ) : liveRunningCount > 0 ? (
          <span className="inline-flex items-center gap-2 text-[12px] font-medium uppercase tracking-[1.4px]">
            <span className="w-1.5 h-1.5 rounded-full bg-bull ds-dot text-bull" />
            <span className="text-bull neon-text-soft">Live</span>
            <span className="text-ink-muted normal-case tracking-normal font-mono text-[11px] ml-1 hidden sm:inline">
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

const TONE_CLS: Record<string, string> = {
  primary: "text-ink-primary",
  bull: "text-bull",
  bear: "text-bear",
  muted: "text-ink-muted",
};

function PulseStat({
  label,
  value,
  sub,
  valueTone = "primary",
}: {
  label: string;
  value: string;
  sub?: string;
  valueTone?: string;
}) {
  return (
    <div className="flex flex-col items-start px-3 leading-none">
      <span className="text-[9px] uppercase tracking-[1.4px] text-ink-muted mb-1">
        {label}
      </span>
      <span className="flex items-baseline gap-1.5">
        <span className={`font-mono text-[13px] font-semibold tabular-nums ${TONE_CLS[valueTone]}`}>
          {value}
        </span>
        {sub && (
          <span className={`font-mono text-[10px] tabular-nums ${TONE_CLS[valueTone]} opacity-70`}>
            {sub}
          </span>
        )}
      </span>
    </div>
  );
}

function Divider() {
  return <span className="w-px h-6 bg-glass-border" />;
}

// XAU mark with a flash on tick direction (green up / red down).
function XauTicker({ price }: { price: number | null }) {
  const prev = useRef<number | null>(null);
  const [dir, setDir] = useState<0 | 1 | -1>(0);
  useEffect(() => {
    if (price == null) return;
    const p = prev.current;
    if (p != null && price !== p) setDir(price > p ? 1 : -1);
    prev.current = price;
  }, [price]);

  const tone = dir === 1 ? "text-bull" : dir === -1 ? "text-bear" : "text-ink-primary";
  const arrow = dir === 1 ? "▲" : dir === -1 ? "▼" : "";
  return (
    <div className="flex flex-col items-start px-3 leading-none">
      <span className="text-[9px] uppercase tracking-[1.4px] text-ink-muted mb-1">XAU / USD</span>
      <span className="flex items-baseline gap-1">
        <span className={`font-mono text-[13px] font-semibold tabular-nums transition-colors duration-300 ${tone}`}>
          {price == null ? "—" : price.toFixed(2)}
        </span>
        {arrow && <span className={`text-[9px] ${tone}`}>{arrow}</span>}
      </span>
    </div>
  );
}
