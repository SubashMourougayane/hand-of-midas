import { Trade } from "../lib/api";
import { Pill } from "./Pill";
import { RangeBar } from "./RangeBar";
import { fmtMoney, fmtPrice, fmtR, colorForR } from "../lib/format";
import { sideLabel } from "../lib/labels";
import { AnimatedNumber } from "./ui/AnimatedNumber";
import { CopyTag } from "./ui/CopyTag";

const CONTRACT: Record<string, number> = {
  XAUUSD: 100, BRENT: 1000, EURUSD: 100_000, GBPUSD: 100_000, USDJPY: 100_000,
};
const contractFor = (sym?: string | null) =>
  CONTRACT[(sym ?? "").replace(/\.ecn$/i, "")] ?? 100;

export function PositionCard({
  trade,
  currentPrice,
  unrealR,
  liveUsd,
  liveLots,
  bookedUsd,
  liveSl,
  now,
  onClick,
}: {
  trade: Trade;
  currentPrice?: number | null;
  unrealR?: number | null;
  liveUsd?: number | null;
  liveLots?: number | null;
  /** realised $ already booked (partial-TP) on this position, if any */
  bookedUsd?: number | null;
  /** live broker SL (MT5 truth). When at/through entry → position is at BE. */
  liveSl?: number | null;
  /** epoch ms for the live hold timer */
  now?: number;
  onClick?: () => void;
}) {
  const tone = trade.side > 0 ? "bull" : "bear";

  // Effective stop = live broker SL when we have it, else the DB stop. This is
  // what actually protects the position, so risk + the range bar must use it.
  const effStop = liveSl != null && liveSl > 0 ? liveSl : trade.stop_price;
  // Breakeven = stop has reached (or passed) entry: long stop>=entry, short stop<=entry.
  const atBE =
    trade.side > 0 ? effStop >= trade.entry_price - 1e-6 : effStop <= trade.entry_price + 1e-6;

  const storedQty = Number(
    (trade.raw_features as Record<string, unknown> | null)?.["qty_lots"]
  );
  const lots =
    liveLots != null && liveLots > 0
      ? liveLots
      : Number.isFinite(storedQty) && storedQty > 0
      ? storedQty
      : null;

  const contract = contractFor(trade.symbol);
  // REAL $ risk = stop distance × lots × contract (not the 1-lot fantasy).
  const riskUsd =
    lots != null ? (trade.risk_units ?? 0) * lots * contract : null;
  // If-win / if-lose expectancy at current size.
  const tp = trade.take_profit_price;
  const winUsd =
    lots != null && tp != null
      ? (tp - trade.entry_price) * trade.side * lots * contract
      : null;
  const loseUsd =
    lots != null
      ? (effStop - trade.entry_price) * trade.side * lots * contract
      : null;

  const hasBooked = bookedUsd != null && Math.abs(bookedUsd) > 0.001;
  const pnlTone = liveUsd == null ? "text-ink-muted" : liveUsd >= 0 ? "text-bull" : "text-bear";
  const pnlSign = liveUsd != null && liveUsd >= 0 ? "+" : liveUsd != null ? "−" : "";

  // Live hold timer.
  const heldMs =
    now != null && trade.entry_timestamp
      ? now - new Date(trade.entry_timestamp).getTime()
      : null;

  return (
    <div
      onClick={onClick}
      className="group rounded-ds bg-glass border border-glass-border hover:shadow-ds-hover transition-all duration-ds cursor-pointer p-3.5 space-y-3"
    >
      {/* Header: side + symbol + entry (+PTP badge) · running $ P&L */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Pill tone={tone} glow>{sideLabel(trade.side)}</Pill>
          <span className="font-mono text-ds-md font-semibold text-ink-primary truncate">
            {trade.symbol?.replace(/\.ecn$/i, "") ?? "—"}
          </span>
          <span className="font-mono text-ds-xs text-ink-muted">
            @ {fmtPrice(trade.entry_price)}
          </span>
          {trade.broker_ticket && (
            <CopyTag
              text={`#${trade.broker_ticket}`}
              value={trade.broker_ticket}
              title={`Copy ticket ${trade.broker_ticket}`}
              className="text-ds-xs text-ink-dim"
            />
          )}
          {hasBooked && (
            <Pill tone="bull">PART-CLOSED</Pill>
          )}
        </div>
        <div className="flex flex-col items-end leading-none shrink-0">
          {!hasBooked ? (
            <>
              {/* No partial: single floating $ + R. */}
              <span className={`font-mono text-ds-xl font-bold tabular-nums ${pnlTone}`}>
                <AnimatedNumber
                  numeric={liveUsd ?? null}
                  value={liveUsd == null ? "—" : `${pnlSign}${fmtMoney(Math.abs(liveUsd), 2)}`}
                />
              </span>
              <span className={`font-mono text-ds-xs mt-1 ${colorForR(unrealR)}`}>
                {fmtR(unrealR)}R <span className="text-ink-dim uppercase">floating</span>
              </span>
            </>
          ) : (
            /* Partial taken → big TOTAL, then a one-line formula underneath:
               "+$85 booked + +$317 floating = +$402 total". */
            <>
              <span className={`font-mono text-ds-xl font-bold tabular-nums ${colorForR((liveUsd ?? 0) + (bookedUsd ?? 0))}`}>
                {(((liveUsd ?? 0) + (bookedUsd ?? 0)) >= 0 ? "+" : "−")}
                {fmtMoney(Math.abs((liveUsd ?? 0) + (bookedUsd ?? 0)), 2)}
                <span className="text-ds-xs text-ink-dim uppercase ml-1">total</span>
              </span>
              <span className="font-mono text-ds-xs mt-1 tabular-nums">
                <span className={colorForR(bookedUsd)}>
                  {bookedUsd! >= 0 ? "+" : "−"}{fmtMoney(Math.abs(bookedUsd!), 0)}
                </span>
                <span className="text-ink-dim"> booked + </span>
                <span className={colorForR(liveUsd)}>
                  {(liveUsd ?? 0) >= 0 ? "+" : "−"}{fmtMoney(Math.abs(liveUsd ?? 0), 0)}
                </span>
                <span className="text-ink-dim"> float</span>
              </span>
            </>
          )}
        </div>
      </div>

      {/* Range bar */}
      <RangeBar
        side={trade.side as 1 | -1}
        entry={trade.entry_price}
        stop={effStop}
        tp={trade.take_profit_price ?? trade.entry_price}
        current={currentPrice}
      />

      {/* Stats row — compact. Risk (red) + Reward (green) side by side.
          Reflows 2→3→5 cols so the cells never squash on a phone. */}
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 pt-1">
        <Stat label="Size" value={
          <span className="font-mono text-ink-primary">
            {lots != null ? `${lots.toFixed(2)}` : "—"}
          </span>
        }/>
        <Stat label={atBE ? "Risk · BE" : "Risk"} value={
          atBE ? (
            <span className="font-mono text-ink-secondary" title="Stop at breakeven (entry) — no downside risk on the remainder.">
              $0 <span className="text-ds-xs text-ink-muted uppercase">be</span>
            </span>
          ) : (
            <span className="font-mono text-bear">
              {loseUsd != null ? fmtMoney(loseUsd, 0) : riskUsd != null ? `−${fmtMoney(riskUsd, 0).replace("$", "$")}` : "—"}
            </span>
          )
        }/>
        <Stat label="Reward" value={
          <span className="font-mono text-bull">
            {winUsd != null ? `+${fmtMoney(winUsd, 0)}` : "—"}
          </span>
        }/>
        <Stat label="R:R" value={
          <span className="font-mono text-ink-secondary">
            {atBE
              ? "∞"
              : winUsd != null && loseUsd != null && Math.abs(loseUsd) > 1e-6
              ? (Math.abs(winUsd / loseUsd)).toFixed(1)
              : "—"}
          </span>
        }/>
        <Stat label="Held" value={
          <span className="font-mono text-ink-secondary tabular-nums">
            {heldMs != null ? fmtDuration(heldMs) : "—"}
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

// ms → "3h 12m" / "12m 04s" (live-ticking hold time).
function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}
