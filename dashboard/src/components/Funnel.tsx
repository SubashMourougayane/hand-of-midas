import { FunnelBucket } from "../lib/api";
import { bgForGateStatus } from "../lib/format";
import { gateLabel } from "../lib/labels";

// Stage groups — the 3 headline funnel steps.
const PIVOT = "GATE_PIVOT_DETECTED";
const SETUP = ["GATE_SETUP_BUILT"];
const PASSED = "GATE_SIGNAL_PASSED";

export function Funnel({
  buckets,
  total,
}: {
  buckets: FunnelBucket[];
  total?: number;
}) {
  void total;
  if (buckets.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-ink-muted text-ds-sm">
        Awaiting first signal…
      </div>
    );
  }

  const by = (s: string) => buckets.find((b) => b.status === s)?.count ?? 0;
  const pivots = by(PIVOT);
  const setups = SETUP.reduce((s, k) => s + by(k), 0);
  const passed = by(PASSED);

  // Everything that isn't a headline stage = a drop-off reason.
  const dropReasons = buckets
    .filter((b) => b.status !== PIVOT && !SETUP.includes(b.status) && b.status !== PASSED)
    .filter((b) => b.count > 0)
    .sort((a, b) => b.count - a.count);
  const dropTotal = dropReasons.reduce((s, b) => s + b.count, 0) || 1;

  const conv = pivots > 0 ? (passed / pivots) * 100 : 0;

  return (
    <div className="px-4 py-3 space-y-4">
      {/* ── Headline funnel: 3 stages + conversion ── */}
      <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-1">
        <Stage label="Pivots" value={pivots} tone="info" />
        <Arrow />
        <Stage label="Setups" value={setups} tone="info" />
        <Arrow />
        <Stage label="Signals" value={passed} tone="bull" />
      </div>
      <div className="flex items-center justify-center">
        <span className="font-mono text-ds-xs text-ink-muted">
          conversion{" "}
          <span className={conv > 0 ? "text-bull" : "text-ink-secondary"}>
            {conv.toFixed(1)}%
          </span>{" "}
          · {passed} of {pivots} pivots became trades
        </span>
      </div>

      {/* ── Where candidates drop out (compact, ranked) ── */}
      {dropReasons.length > 0 && (
        <div className="space-y-1.5 pt-1 border-t border-glass-border">
          <div className="text-ds-xs uppercase tracking-[0.14em] text-ink-dim pt-2">
            Dropped at
          </div>
          {dropReasons.slice(0, 6).map((b) => {
            const pct = (b.count / dropTotal) * 100;
            const color = bgForGateStatus(b.status);
            return (
              <div key={b.status} className="flex items-center gap-2.5">
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: color }}
                />
                <span className="text-ds-xs text-ink-secondary flex-1 truncate">
                  {gateLabel(b.status)}
                </span>
                <div className="w-20 h-1 rounded-full bg-white/[0.05] overflow-hidden shrink-0">
                  <div
                    className="h-full rounded-full transition-[width] duration-500"
                    style={{ width: `${pct}%`, background: color }}
                  />
                </div>
                <span className="font-mono text-ds-xs text-ink-primary w-10 text-right tabular-nums">
                  {b.count.toLocaleString()}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Stage({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "info" | "bull";
}) {
  return (
    <div className="flex flex-col items-center text-center">
      <span
        className={`font-mono text-ds-2xl font-bold tabular-nums ${
          tone === "bull" ? "text-bull" : "text-ink-primary"
        }`}
      >
        {value.toLocaleString()}
      </span>
      <span className="text-ds-xs uppercase tracking-wide text-ink-muted mt-0.5">
        {label}
      </span>
    </div>
  );
}

function Arrow() {
  return <span className="text-ink-dim text-ds-md px-1">→</span>;
}
