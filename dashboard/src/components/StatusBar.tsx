import { useEffect, useState } from "react";
import { fmtMoney, fmtTs } from "../lib/format";
import { WsStatus } from "../lib/ws";
import { SessionClocks } from "./SessionClocks";

export function StatusBar({
  status,
  lastMessageAt,
  runRef,
  equity,
  balance,
  openPositions,
  signalsSeen,
}: {
  status: WsStatus;
  lastMessageAt: number;
  runRef?: string;
  equity?: number | null;
  balance?: number | null;
  openPositions?: number | null;
  signalsSeen?: number;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const age = lastMessageAt ? Math.round((now - lastMessageAt) / 1000) : -1;
  const dotCls =
    status !== "open"
      ? "bg-bear text-bear"
      : age > 5
      ? "bg-warn text-warn"
      : "bg-bull text-bull";

  return (
    <div className="flex items-center justify-between border-t border-glass-border bg-glass-subtle backdrop-blur-xl px-4 h-7 shrink-0 text-ds-xs">
      <div className="flex items-center gap-4">
        <span className="inline-flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ds-dot ${dotCls}`} />
          <span className="uppercase tracking-wide text-ink-secondary font-medium">
            {status}
          </span>
          {status === "open" && age >= 0 && (
            <span className="text-ink-muted font-mono">+{age}s</span>
          )}
        </span>
        {runRef && (
          <span className="text-ink-muted">
            run <span className="text-ink-secondary font-mono">{runRef.slice(-12)}</span>
          </span>
        )}
        {signalsSeen != null && (
          <span className="text-ink-muted">
            signals <span className="text-ink-secondary font-mono">{signalsSeen}</span>
          </span>
        )}
      </div>

      {/* Center: market-session clocks */}
      <SessionClocks now={now} />

      <div className="flex items-center gap-4">
        {balance != null && (
          <span className="text-ink-muted">
            balance{" "}
            <span className="text-ink-secondary font-mono">{fmtMoney(balance)}</span>
          </span>
        )}
        {equity != null && (
          <span className="text-ink-muted">
            equity{" "}
            <span className="text-bull font-mono font-medium">{fmtMoney(equity)}</span>
          </span>
        )}
        {openPositions != null && (
          <span className="text-ink-muted">
            open <span className="text-ink-secondary font-mono">{openPositions}</span>
          </span>
        )}
        <span className="text-ink-muted font-mono">
          {fmtTs(new Date(now).toISOString())} UTC
        </span>
      </div>
    </div>
  );
}
