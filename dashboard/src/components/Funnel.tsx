import { FunnelBucket } from "../lib/api";
import { bgForGateStatus, shortGateLabel } from "../lib/format";

// Ranked bucket order — funnel hierarchy from "everything happens" to "rare success".
const RANK = [
  "GATE_PIVOT_DETECTED",
  "GATE_SETUP_BUILT",
  "GATE_SETUP_INVALIDATED",
  "GATE_SETUP_EXPIRED",
  "GATE_SIGNAL_STRICT_AFTER_FAIL",
  "GATE_SIGNAL_ZONE_MISS",
  "GATE_SIGNAL_SESSION_FAIL",
  "GATE_SIGNAL_REGIME_FAIL",
  "GATE_SIGNAL_CONFIRM_FAIL",
  "GATE_FINALIZE_RISK_INVALID",
  "GATE_FINALIZE_RISK_PCT_CAP",
  "GATE_FINALIZE_MIN_RISK_FLOOR",
  "GATE_FINALIZE_DEDUP_COLLISION",
  "GATE_SIGNAL_PASSED",
];

export function Funnel({
  buckets,
  total,
}: {
  buckets: FunnelBucket[];
  total?: number;
}) {
  if (buckets.length === 0) {
    return (
      <div className="px-3 py-6 text-center text-ink-muted text-ds-sm">
        Awaiting first signal…
      </div>
    );
  }

  const ordered = [...buckets].sort((a, b) => {
    const ai = RANK.indexOf(a.status);
    const bi = RANK.indexOf(b.status);
    if (ai >= 0 && bi >= 0) return ai - bi;
    if (ai >= 0) return -1;
    if (bi >= 0) return 1;
    return b.count - a.count;
  });
  const max = ordered.reduce((m, b) => Math.max(m, b.count), 0) || 1;
  const totalCount = total ?? ordered.reduce((s, b) => s + b.count, 0);

  return (
    <div className="px-3 py-2 space-y-1">
      {ordered.map((b) => {
        const widthPct = Math.max(2, Math.round((b.count / max) * 100));
        const sharePct = totalCount ? (b.count / totalCount) * 100 : 0;
        const color = bgForGateStatus(b.status);
        return (
          <div key={b.status} className="group relative">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-ds-xs text-ink-secondary capitalize flex-1 truncate">
                {shortGateLabel(b.status)}
              </span>
              <span className="font-mono text-ds-xs text-ink-primary w-12 text-right">
                {b.count.toLocaleString()}
              </span>
              <span className="font-mono text-ds-xs text-ink-muted w-12 text-right">
                {sharePct.toFixed(1)}%
              </span>
            </div>
            <div className="h-1.5 bg-bg-input rounded-full overflow-hidden">
              <div
                className="h-full transition-all duration-ds rounded-full"
                style={{ width: `${widthPct}%`, background: color, opacity: 0.85 }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
