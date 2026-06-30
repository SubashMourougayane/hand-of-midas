import { Link, useLocation } from "react-router-dom";
import { Run } from "../lib/api";

const TABS = [
  { to: "/live", label: "LIVE" },
  { to: "/journal", label: "JOURNAL" },
  { to: "/trades", label: "TRADES" },
  { to: "/signals", label: "SIGNALS" },
];

export function TopBar({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: Run[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
}) {
  const loc = useLocation();
  return (
    <div className="flex items-center justify-between border-b border-term-amber bg-term-panel px-2 py-0.5 text-term-sm">
      <div className="flex items-center gap-1">
        <span className="text-term-amber font-bold uppercase mr-2">
          bt_engine
        </span>
        {TABS.map((t) => {
          const active = loc.pathname.startsWith(t.to);
          return (
            <Link
              key={t.to}
              to={t.to}
              className={`px-2 py-0.5 uppercase tracking-wider border ${
                active
                  ? "border-term-amber text-term-amber bg-term-bg"
                  : "border-transparent text-term-textMuted hover:text-term-amber"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
      </div>
      <div>
        <select
          className="bg-term-bg border border-term-amber text-term-amber px-1 py-0.5 text-term-sm"
          value={selectedRunId ?? ""}
          onChange={(e) => onSelectRun(e.target.value)}
        >
          {runs.length === 0 && <option value="">(no runs)</option>}
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              [{r.mode.toUpperCase()}] {r.strategy_id} · {r.run_ref.slice(-8)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
