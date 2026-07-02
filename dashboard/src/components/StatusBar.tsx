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

  // Feed health only on the left; sessions center; UTC clock right. Account
  // figures live in the Live cockpit — footer stays clean + globally useful.
  void runRef; void balance; void equity; void openPositions; void signalsSeen;
  const utc = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "UTC",
  }).format(new Date(now));

  return (
    <div className="flex items-center justify-between border-t border-glass-border bg-glass-subtle backdrop-blur-xl px-4 h-7 shrink-0 text-ds-xs">
      <div className="flex items-center gap-2 shrink-0">
        <span className={`w-1.5 h-1.5 rounded-full ds-dot ${dotCls}`} />
        <span className="uppercase tracking-wide text-ink-secondary font-medium">
          {status === "open" ? (age > 5 ? "STALE" : "LIVE") : status}
        </span>
        {status === "open" && age >= 0 && (
          <span className="text-ink-dim font-mono">{age}s</span>
        )}
      </div>

      {/* Center: market-session clocks (the useful bit) */}
      <SessionClocks now={now} />

      <div className="flex items-center gap-2 shrink-0">
        <span className="font-mono text-ink-secondary tabular-nums">{utc}</span>
        <span className="text-ink-dim uppercase tracking-wide">UTC</span>
      </div>
    </div>
  );
}
