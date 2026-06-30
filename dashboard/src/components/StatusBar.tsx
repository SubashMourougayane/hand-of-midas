import { useEffect, useState } from "react";
import { fmtTs } from "../lib/format";
import { WsStatus } from "../lib/ws";

export function StatusBar({
  status,
  lastMessageAt,
  runRef,
  equity,
}: {
  status: WsStatus;
  lastMessageAt: number;
  runRef?: string;
  equity?: number | null;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const age = lastMessageAt ? Math.round((now - lastMessageAt) / 1000) : -1;
  const dotColor =
    status !== "open"
      ? "bg-term-red"
      : age > 5
      ? "bg-term-amber"
      : "bg-term-green";

  return (
    <div className="flex items-center justify-between border-t border-term-amber bg-term-panel px-2 py-0.5 text-term-xs">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1">
          <span className={`inline-block w-2 h-2 ${dotColor} term-blink`} />
          <span className="uppercase">{status}</span>
          {status === "open" && age >= 0 && (
            <span className="text-term-textMuted">+{age}s</span>
          )}
        </span>
        {runRef && (
          <span className="text-term-textMuted">
            RUN <span className="text-term-amber">{runRef}</span>
          </span>
        )}
      </div>
      <div className="flex items-center gap-3">
        {equity != null && (
          <span>
            EQUITY <span className="text-term-green">${equity.toFixed(2)}</span>
          </span>
        )}
        <span className="text-term-textMuted">{fmtTs(new Date(now).toISOString())} UTC</span>
      </div>
    </div>
  );
}
