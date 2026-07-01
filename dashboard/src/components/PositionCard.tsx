import { Trade } from "../lib/api";
import { Pill } from "./Pill";
import { RangeBar } from "./RangeBar";
import { fmtMoney, fmtPrice, fmtR, fmtTime, colorForR } from "../lib/format";

export function PositionCard({
  trade,
  currentPrice,
  unrealR,
  onClick,
}: {
  trade: Trade;
  currentPrice?: number | null;
  unrealR?: number | null;
  onClick?: () => void;
}) {
  const isLong = trade.side > 0;
  const tone = isLong ? "bull" : "bear";

  return (
    <div
      onClick={onClick}
      className={`
        group rounded-ds bg-bg-elevated border border-line-subtle
        hover:border-line-base hover:shadow-ds-hover
        transition-all duration-ds cursor-pointer
        p-3 space-y-2
      `}
    >
      {/* Header: leg name + side pill + status */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-ds-md font-semibold text-ink-primary truncate">
            {trade.leg ?? "—"}
          </span>
          <Pill tone={tone} glow>
            {isLong ? "LONG" : "SHORT"}
          </Pill>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-ds-xs text-ink-muted">
            {fmtTime(trade.entry_timestamp)}
          </span>
          <Pill tone="info">OPEN</Pill>
        </div>
      </div>

      {/* Range bar */}
      <RangeBar
        side={trade.side as 1 | -1}
        entry={trade.entry_price}
        stop={trade.stop_price}
        tp={trade.take_profit_price ?? trade.entry_price}
        current={currentPrice}
      />

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-2 pt-1">
        <Stat label="UNREAL" value={
          <span className={`font-mono ${colorForR(unrealR)}`}>{fmtR(unrealR)}R</span>
        }/>
        <Stat label="RISK" value={
          <span className="font-mono text-ink-primary">{fmtPrice(trade.risk_units)}</span>
        }/>
        <Stat label="$ RISK" value={
          <span className="font-mono text-ink-secondary">
            {fmtMoney((trade.risk_units ?? 0) * 100, 0)}
          </span>
        }/>
        <Stat label="REGIME" value={
          <span className="text-ds-xs text-ink-secondary truncate inline-block">
            {trade.regime ?? "—"}
          </span>
        }/>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-ds-xs text-ink-muted uppercase tracking-wide">{label}</div>
      <div className="text-ds-sm">{value}</div>
    </div>
  );
}
