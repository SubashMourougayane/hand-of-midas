import { useMemo } from "react";
import { BarWalkRow, JournalEvt, Trade } from "../lib/api";
import { KPI } from "./KPI";
import { Pane } from "./Pane";
import { Pill } from "./Pill";
import { AnnotatedBarWalk } from "./AnnotatedBarWalk";
import { EventTimeline, SyntheticEvt } from "./EventTimeline";
import { legName, sideLabel, regimeLabel } from "../lib/labels";
import {
  barsToDuration,
  colorForR,
  fmtMoney,
  fmtPriceFor,
  fmtR,
  fmtRiskFor,
  fmtTs,
  tradePnlReal,
} from "../lib/format";

function fibNum(rf: Record<string, unknown> | null | undefined, key: string): number | null {
  if (!rf) return null;
  const v = rf[key];
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (!Number.isNaN(n)) return n;
  }
  return null;
}

// Peak MFE / worst MAE across the bar walk (R-multiples).
function excursions(walk: BarWalkRow[]): { mfe: number | null; mae: number | null } {
  let mfe: number | null = null;
  let mae: number | null = null;
  for (const b of walk) {
    if (b.mfe_r != null) mfe = mfe == null ? b.mfe_r : Math.max(mfe, b.mfe_r);
    if (b.mae_r != null) mae = mae == null ? b.mae_r : Math.min(mae, b.mae_r);
  }
  return { mfe, mae };
}

// Signed R-multiple of a price relative to entry, in the trade's direction.
function priceToR(price: number, trade: Trade): number | null {
  const risk = Math.abs(trade.entry_price - trade.stop_price);
  if (risk === 0) return null;
  const dir = trade.side > 0 ? 1 : -1;
  return ((price - trade.entry_price) * dir) / risk;
}

export function TradeStory({
  trade,
  journal,
  walk,
  symbol,
  timeframe,
}: {
  trade: Trade;
  journal: JournalEvt[];
  walk: BarWalkRow[];
  symbol: string | null;
  timeframe: string;
}) {
  const long = trade.side > 0;
  const closed = trade.exit_timestamp != null;
  const statusLabel = closed ? (trade.exit_reason ?? "closed").toUpperCase() : "OPEN";
  const pnl = tradePnlReal(symbol, trade.net_r, trade.risk_units, trade.raw_features, trade.broker_net_usd);

  const { mfe, mae } = useMemo(() => excursions(walk), [walk]);

  // R:R = (TP distance) / (SL distance) from entry.
  const rr = useMemo(() => {
    if (trade.take_profit_price == null) return null;
    const risk = Math.abs(trade.entry_price - trade.stop_price);
    const reward = Math.abs(trade.take_profit_price - trade.entry_price);
    if (risk === 0) return null;
    return reward / risk;
  }, [trade]);

  const fib382 = fibNum(trade.raw_features, "fib_382");
  const fib786 = fibNum(trade.raw_features, "fib_786");
  const fibL = fibNum(trade.raw_features, "fib_L");
  const fibH = fibNum(trade.raw_features, "fib_H");
  const hasFib = fib382 != null || fib786 != null || fibL != null || fibH != null;

  // Synthetic "current state" row — only for OPEN trades, so the timeline
  // feels alive even when ENTRY_FILL is the sole real event.
  const synthetic = useMemo<SyntheticEvt | null>(() => {
    if (closed || walk.length === 0) return null;
    const last = walk[walk.length - 1];
    const unrealR =
      last.unrealised_r != null ? last.unrealised_r : priceToR(last.close, trade);
    const detail: Record<string, unknown> = {
      bars_elapsed: walk.length,
      unrealised_r: unrealR,
      last_price: last.close,
    };
    if (trade.take_profit_price != null) {
      const r = priceToR(trade.take_profit_price, trade);
      if (r != null) detail.to_tp_r = r - (unrealR ?? 0);
    }
    const rSl = priceToR(trade.stop_price, trade);
    if (rSl != null) detail.to_sl_r = rSl - (unrealR ?? 0);
    return { synthetic: true, ts: last.bar_ts, event_type: "OPEN_STATE", detail };
  }, [closed, walk, trade]);

  // Context sub-text for MFE / MAE.
  const partialTarget = 1; // partial TP fires at +1R in this strategy.
  const mfeSub =
    mfe == null
      ? undefined
      : trade.partial_taken
      ? "partial taken"
      : mfe < partialTarget
      ? `never reached +${partialTarget}R partial`
      : "cleared partial trigger";
  const maeSub =
    mae == null ? undefined : mae <= -1 ? "went beyond −1R (stop risk)" : "held above −1R";

  return (
    <div className="flex flex-col gap-2.5 min-h-0">
      {/* ── Header card ── */}
      <Pane padded>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <Pill tone={long ? "bull" : "bear"} glow>
                {sideLabel(trade.side)}
              </Pill>
              <span className="text-ink-primary font-semibold text-ds-lg tracking-tight">
                {symbol ?? "—"}
              </span>
              {trade.leg && <Pill tone="muted">{legName(trade.leg)}</Pill>}
              {trade.regime && trade.regime.toLowerCase() !== "any" && (
                <Pill tone="info">{regimeLabel(trade.regime)}</Pill>
              )}
              <Pill tone={closed ? (statusLabel === "SL" ? "bear" : "bull") : "info"}>
                {statusLabel}
              </Pill>
              {trade.overnight != null && (
                <Pill tone={trade.overnight ? "bull" : "muted"}>
                  {trade.overnight ? "OVERNIGHT" : "SAME-DAY"}
                </Pill>
              )}
              {trade.partial_taken && <Pill tone="warn">PARTIAL</Pill>}
            </div>
            <div className="text-ds-xs text-ink-muted font-mono">
              {trade.trade_ref} · entered {fmtTs(trade.entry_timestamp)}
              {closed && trade.exit_timestamp && ` · exited ${fmtTs(trade.exit_timestamp)}`}
            </div>
          </div>
          <div className="flex items-baseline gap-5">
            <div className="text-right">
              <div className={`font-mono font-semibold text-ds-3xl leading-none ${colorForR(trade.net_r)}`}>
                {fmtR(trade.net_r)}R
              </div>
              <div className="text-ds-xs uppercase tracking-wide text-ink-muted mt-1">
                {closed ? "net r-multiple" : "unrealised r"}
              </div>
            </div>
            {pnl != null && (
              <div className="text-right">
                <div className={`font-mono font-semibold text-ds-xl leading-none ${pnl >= 0 ? "text-bull" : "text-bear"}`}>
                  {fmtMoney(pnl, 0)}
                </div>
                <div className="text-ds-xs uppercase tracking-wide text-ink-muted mt-1">
                  {closed ? "realised p&l" : "open p&l"}
                </div>
              </div>
            )}
          </div>
        </div>
      </Pane>

      {/* ── Geometry KPI strip ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <KPI label="Entry" value={fmtPriceFor(symbol, trade.entry_price)} />
        <KPI label="Stop" value={fmtPriceFor(symbol, trade.stop_price)} />
        <KPI label="Take Profit" value={fmtPriceFor(symbol, trade.take_profit_price)} />
        <KPI label="Risk / 1R" value={fmtRiskFor(symbol, trade.risk_units)} />
        <KPI label="R:R" value={rr != null ? `${rr.toFixed(2)}` : "—"} />
        <KPI
          label="Bars Held"
          value={trade.bars_held != null ? String(trade.bars_held) : String(walk.length || "—")}
          sub={barsToDuration(trade.bars_held ?? walk.length, timeframe)}
        />
        <KPI
          label="MFE"
          value={mfe != null ? `${fmtR(mfe)}R` : "—"}
          deltaTone="bull"
          sub={mfeSub}
        />
        <KPI
          label="MAE"
          value={mae != null ? `${fmtR(mae)}R` : "—"}
          deltaTone="bear"
          sub={maeSub}
        />
      </div>

      {/* ── Fib geometry (optional) ── */}
      {hasFib && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <KPI label="Fib Low" value={fmtPriceFor(symbol, fibL)} />
          <KPI label="Fib High" value={fmtPriceFor(symbol, fibH)} />
          <KPI label="Fib 0.382" value={fmtPriceFor(symbol, fib382)} />
          <KPI label="Fib 0.786" value={fmtPriceFor(symbol, fib786)} />
        </div>
      )}

      {/* ── Chart + timeline ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-2.5">
        <Pane
          title="Bar Walk"
          subtitle={`${walk.length} bars`}
          right={
            <span className="font-mono text-ds-xs text-ink-muted">
              entry · SL · TP · fib zone
            </span>
          }
          className="lg:col-span-3 h-[440px]"
        >
          <AnnotatedBarWalk walk={walk} trade={trade} symbol={symbol} />
        </Pane>
        <Pane
          title="Trade Story"
          subtitle={`${journal.length} event${journal.length === 1 ? "" : "s"}`}
          right={!closed ? <Pill tone="info">LIVE</Pill> : undefined}
          className="lg:col-span-2 h-[440px]"
        >
          <EventTimeline events={journal} synthetic={synthetic} />
        </Pane>
      </div>
    </div>
  );
}
