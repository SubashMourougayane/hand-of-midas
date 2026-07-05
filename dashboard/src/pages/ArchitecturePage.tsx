import { useState } from "react";
import { TrendingUp, TrendingDown, Zap } from "lucide-react";

/**
 * Architecture — visual rulebook for A (LONG) and D (SHORT) setups.
 * Three-tab layout: LONG, SHORT, Live Loop (per-15min-tick data flow).
 */
export function ArchitecturePage() {
  const [tab, setTab] = useState<"long" | "short" | "live">("long");
  return (
    <div className="h-full overflow-auto px-4 sm:px-6 py-5">
      <div className="max-w-[1400px] mx-auto space-y-4 anim-fade-up">
        <header className="flex flex-col gap-3 lg:flex-row lg:items-baseline lg:justify-between">
          <div>
            <h1 className="text-ds-2xl font-semibold text-ink-primary tracking-tight">
              Strategy Rulebook
            </h1>
            <p className="text-ds-sm text-ink-muted mt-1">
              Fib V2 intraday · M15 base · lb=3 pivot confirmation · PTP+1R · $0.65 broker cost
            </p>
          </div>
          <div className="flex items-center gap-1 glass rounded-ds p-1 overflow-x-auto scroll-slim max-w-full">
            <TabBtn
              active={tab === "long"}
              onClick={() => setTab("long")}
              tone="bull"
              icon={<TrendingUp size={14} />}
              label="Long"
              sub="12h hold · London / NY"
            />
            <TabBtn
              active={tab === "short"}
              onClick={() => setTab("short")}
              tone="bear"
              icon={<TrendingDown size={14} />}
              label="Short"
              sub="24h hold · all sessions"
            />
            <TabBtn
              active={tab === "live"}
              onClick={() => setTab("live")}
              tone="info"
              icon={<Zap size={14} />}
              label="LIVE LOOP"
              sub="per-15min-tick data flow"
            />
          </div>
        </header>

        {tab === "long" ? <LongFlow /> : tab === "short" ? <ShortFlow /> : <LiveLoopFlow />}

        {tab !== "live" && <SharedRules />}
      </div>
    </div>
  );
}

function TabBtn({
  active, onClick, tone, icon, label, sub,
}: {
  active: boolean; onClick: () => void; tone: "bull" | "bear" | "info";
  icon: React.ReactNode; label: string; sub: string;
}) {
  const toneCls = active
    ? tone === "bull"
      ? "bg-bull/15 text-bull border-bull/40"
      : tone === "bear"
        ? "bg-bear/15 text-bear border-bear/40"
        : "bg-info/15 text-info border-info/40"
    : "text-ink-muted hover:text-ink-secondary border-transparent";
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-ds-sm border ${toneCls} flex items-center gap-2 transition-colors duration-ds`}
    >
      {icon}
      <div className="text-left leading-tight">
        <div className="font-semibold text-ds-sm">{label}</div>
        <div className="text-ds-xs opacity-70">{sub}</div>
      </div>
    </button>
  );
}

// ── FLOW BLOCKS ──

function Step({
  n,
  title,
  desc,
  tone = "neutral",
  detail,
  formula,
}: {
  n: string;
  title: string;
  desc: string;
  tone?: "neutral" | "info" | "bull" | "bear" | "warn" | "success";
  detail?: React.ReactNode;
  formula?: string;
}) {
  const toneMap = {
    neutral: "border-line-base bg-bg-elevated",
    info: "border-info/40 bg-info/[0.05]",
    bull: "border-bull/40 bg-bull/[0.05]",
    bear: "border-bear/40 bg-bear/[0.05]",
    warn: "border-warn/40 bg-warn/[0.05]",
    success: "border-brass/50 bg-brass/[0.08] shadow-ds-glow-bull",
  };
  const nBg = {
    neutral: "bg-line-base text-ink-primary",
    info: "bg-info text-bg-base",
    bull: "bg-bull text-bg-base",
    bear: "bg-bear text-bg-base",
    warn: "bg-warn text-bg-base",
    success: "bg-brass text-bg-base",
  };
  return (
    <div className={`relative border rounded-ds p-4 ${toneMap[tone]}`}>
      <div className="flex items-start gap-3">
        <span className={`shrink-0 w-8 h-8 rounded-full ${nBg[tone]} flex items-center justify-center font-bold text-ds-sm`}>
          {n}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-ds-md font-semibold text-ink-primary mb-0.5">{title}</div>
          <div className="text-ds-sm text-ink-secondary">{desc}</div>
          {formula && (
            <div className="mt-2 font-mono text-ds-xs bg-bg-input border border-line-subtle rounded-ds-sm px-2 py-1 text-ink-primary">
              {formula}
            </div>
          )}
          {detail && <div className="mt-2 text-ds-xs text-ink-muted">{detail}</div>}
        </div>
      </div>
    </div>
  );
}

function Arrow({ tone = "neutral" }: { tone?: "neutral" | "bull" | "bear" }) {
  const cls =
    tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-muted";
  return (
    <div className="flex justify-center py-1">
      <div className={`${cls} text-ds-md`}>↓</div>
    </div>
  );
}

function GateGroup({
  title,
  tone,
  gates,
}: {
  title: string;
  tone: "bull" | "bear";
  gates: { label: string; ok: string; fail: string }[];
}) {
  const border = tone === "bull" ? "border-bull/30" : "border-bear/30";
  return (
    <div className={`border ${border} rounded-ds p-4 bg-bg-surface`}>
      <div className="text-ds-sm font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        {title}
      </div>
      <div className="space-y-2">
        {gates.map((g, i) => (
          <div key={i} className="grid grid-cols-1 md:grid-cols-12 gap-1.5 md:gap-3 items-baseline border-b border-line-subtle md:border-0 pb-2 md:pb-0">
            <div className="md:col-span-3 text-ds-sm text-ink-primary font-medium leading-snug">
              {g.label}
            </div>
            <div className="md:col-span-5 text-ds-xs text-bull grid grid-cols-[14px_1fr] gap-1 leading-snug">
              <span className="text-center">✓</span>
              <span>{g.ok}</span>
            </div>
            <div className="md:col-span-4 text-ds-xs text-bear grid grid-cols-[14px_1fr] gap-1 leading-snug">
              <span className="text-center">✗</span>
              <span>{g.fail}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── LONG FLOW ──

function LongFlow() {
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-7 space-y-0">
        <div className="text-ds-md font-semibold text-bull mb-3 tracking-wide">
          A LEG · LONG ENTRY FLOW
        </div>

        <Step
          n="1"
          title="Pivot detection"
          tone="info"
          desc="Scan M15 bars for confirmed HIGH + LOW pivots. Confirmation = 3 bars either side (lb=3)."
          formula="LOW = min(3 bars left, center, 3 bars right)  ·  HIGH = max(…)"
          detail={<>Emits <code className="text-info">GATE_PIVOT_DETECTED</code> when new pivot confirms 3 bars after its actual formation.</>}
        />
        <Arrow tone="bull" />

        <Step
          n="2"
          title="Pivot ordering check (LONG-specific)"
          tone="bull"
          desc="For a LONG setup, HIGH must confirm AFTER LOW chronologically."
          formula="H_ts > L_ts    (market bottomed, then made new high, now expecting retrace back down)"
          detail={<>Fail → <code className="text-bear">GATE_SETUP_REJECT_PIVOT_ORDER</code></>}
        />
        <Arrow tone="bull" />

        <Step
          n="3"
          title="Fib retrace setup built"
          tone="info"
          desc="From H and L, compute fib levels. Setup lives until invalidated or expired (12h)."
          formula="fib_100 = LOW  ·  fib_382 = H − 0.382×Δ  ·  fib_786 = H − 0.786×Δ  ·  SL = LOW − 0.02×Δ  ·  TP = H + 2.618×Δ"
        />
        <Arrow tone="bull" />

        <Step
          n="4"
          title="Wait for retrace INTO zone"
          desc="Each M15 close checks: is price back inside the 78.6% → 38.2% retrace band?"
          formula="fib_786 ≤ bar.close ≤ fib_382"
          detail={<>Zone miss → <code className="text-bear">GATE_SIGNAL_ZONE_MISS</code> (repeats per bar until in-zone or invalidated)</>}
        />
        <Arrow tone="bull" />

        <GateGroup
          title="Entry gate stack"
          tone="bull"
          gates={[
            {
              label: "Invalidation",
              ok: "close ≥ fib_100 (LOW) — setup still valid",
              fail: "close < LOW → setup killed",
            },
            {
              label: "Zone hit",
              ok: "close inside [78.6%, 38.2%]",
              fail: "close outside — waits next bar",
            },
            {
              label: "Session",
              ok: "NY hour in [3, 17) → London or NY open",
              fail: "outside window — waits",
            },
            {
              label: "Regime",
              ok: "D1 features finite (any regime)",
              fail: "no daily close yet — waits",
            },
            {
              label: "Confirmation candle",
              ok: "bullish engulf OR lower-wick pinbar (wick > 50% of range)",
              fail: "no pattern — waits next bar",
            },
            {
              label: "Strict-after",
              ok: "current bar strictly after setup_confirm_ts",
              fail: "same bar as confirm — skip",
            },
          ]}
        />
        <Arrow tone="bull" />

        <Step
          n="5"
          title="Order queued for NEXT bar open"
          tone="success"
          desc="All gates pass → GATE_SIGNAL_PASSED. Entry price = next M15 open (research-parity)."
          formula="entry = next_bar.open  ·  risk = entry − SL  ·  qty = 1.5% × equity / risk / contract_size"
        />
        <Arrow tone="bull" />

        <GateGroup
          title="Final safety gates"
          tone="bull"
          gates={[
            {
              label: "Risk sanity",
              ok: "0 < risk < 2% × entry",
              fail: "risk ≤ 0 or > 2% → reject",
            },
            {
              label: "Min risk floor",
              ok: "risk_units ≥ $0.50 (XAU broker-tradeable)",
              fail: "risk too tight — reject",
            },
            {
              label: "Dedup",
              ok: "(entry_ts, side, leg) not seen before",
              fail: "duplicate → reject",
            },
            {
              label: "Broker submit",
              ok: "DWX bridge accepts order → filled at market",
              fail: "spread > $0.50 or kill-switch → reject",
            },
          ]}
        />
        <Arrow tone="bull" />

        <Step
          n="6"
          title="Bracket walker — exit logic"
          tone="bull"
          desc="Each subsequent M15 bar walks brackets against high/low."
          detail={
            <ul className="list-disc pl-4 space-y-0.5">
              <li>TP hit (close ≥ TP) → close full at TP</li>
              <li>SL hit (close ≤ SL) → close full at SL</li>
              <li>+1R hit (partial TP) → close 50% at +1R, move SL to breakeven for rest</li>
              <li>12h elapsed (48 M15 bars) → TIMEOUT exit at bar close</li>
            </ul>
          }
        />
      </div>

      <aside className="col-span-12 lg:col-span-5 space-y-3">
        <div className="text-ds-md font-semibold text-transparent mb-3 select-none" aria-hidden>
          .
        </div>
        <div className="border border-bull/40 rounded-ds p-4 bg-bull/[0.05]">
          <div className="text-ds-md font-semibold text-bull mb-2">Locked config · A</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-ds-sm">
            <dt className="text-ink-muted">Direction</dt><dd className="text-ink-primary">LONG</dd>
            <dt className="text-ink-muted">Base TF</dt><dd className="text-ink-primary">M15</dd>
            <dt className="text-ink-muted">Pivot lookback</dt><dd className="text-ink-primary">lb = 3</dd>
            <dt className="text-ink-muted">Session</dt><dd className="text-ink-primary">london_ny (NY 3-17)</dd>
            <dt className="text-ink-muted">Regime</dt><dd className="text-ink-primary">any</dd>
            <dt className="text-ink-muted">Max hold</dt><dd className="text-ink-primary">12h (48 bars)</dd>
            <dt className="text-ink-muted">SL buffer</dt><dd className="text-ink-primary">0.02 × Δ below LOW</dd>
            <dt className="text-ink-muted">TP extension</dt><dd className="text-ink-primary">2.618 × Δ above HIGH</dd>
            <dt className="text-ink-muted">Partial TP</dt><dd className="text-ink-primary">50% @ +1R → SL→BE</dd>
            <dt className="text-ink-muted">Min risk floor</dt><dd className="text-ink-primary">$0.50 / oz</dd>
            <dt className="text-ink-muted">Cost model</dt><dd className="text-ink-primary">$0.65 / trade</dd>
          </dl>
        </div>

        <PriceDiagram side="long" />
      </aside>
    </div>
  );
}

// ── SHORT FLOW ──

function ShortFlow() {
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-7 space-y-0">
        <div className="text-ds-md font-semibold text-bear mb-3 tracking-wide">
          D LEG · SHORT ENTRY FLOW
        </div>

        <Step
          n="1"
          title="Pivot detection"
          tone="info"
          desc="Scan M15 bars for confirmed HIGH + LOW pivots. Confirmation = 3 bars either side (lb=3)."
          formula="HIGH = max(3 bars left, center, 3 bars right)  ·  LOW = min(…)"
          detail={<>Emits <code className="text-info">GATE_PIVOT_DETECTED</code> when new pivot confirms.</>}
        />
        <Arrow tone="bear" />

        <Step
          n="2"
          title="Pivot ordering check (SHORT-specific)"
          tone="bear"
          desc="For a SHORT setup, LOW must confirm AFTER HIGH chronologically."
          formula="L_ts > H_ts    (market peaked, then made new low, now expecting retrace back up)"
          detail={<>Fail → <code className="text-bear">GATE_SETUP_REJECT_PIVOT_ORDER</code></>}
        />
        <Arrow tone="bear" />

        <Step
          n="3"
          title="Fib retrace setup built"
          tone="info"
          desc="From H and L, compute fib levels. Setup lives until invalidated or expired (24h)."
          formula="fib_100 = HIGH  ·  fib_382 = L + 0.382×Δ  ·  fib_786 = L + 0.786×Δ  ·  SL = HIGH + 0.02×Δ  ·  TP = L − 2.618×Δ"
        />
        <Arrow tone="bear" />

        <Step
          n="4"
          title="Wait for retrace INTO zone"
          desc="Each M15 close checks: is price back inside the 38.2% → 78.6% retrace band?"
          formula="fib_382 ≤ bar.close ≤ fib_786"
          detail={<>Zone miss → <code className="text-bear">GATE_SIGNAL_ZONE_MISS</code> (repeats per bar until in-zone or invalidated)</>}
        />
        <Arrow tone="bear" />

        <GateGroup
          title="Entry gate stack"
          tone="bear"
          gates={[
            {
              label: "Invalidation",
              ok: "close ≤ fib_100 (HIGH) — setup still valid",
              fail: "close > HIGH → setup killed",
            },
            {
              label: "Zone hit",
              ok: "close inside [38.2%, 78.6%]",
              fail: "close outside — waits next bar",
            },
            {
              label: "Session",
              ok: "all sessions allowed (D leg has no session filter)",
              fail: "n/a — always passes",
            },
            {
              label: "Regime",
              ok: "D1 features finite (any regime)",
              fail: "no daily close yet — waits",
            },
            {
              label: "Confirmation candle",
              ok: "bearish engulf OR upper-wick pinbar (wick > 50% of range)",
              fail: "no pattern — waits next bar",
            },
            {
              label: "Strict-after",
              ok: "current bar strictly after setup_confirm_ts",
              fail: "same bar as confirm — skip",
            },
          ]}
        />
        <Arrow tone="bear" />

        <Step
          n="5"
          title="Order queued for NEXT bar open"
          tone="success"
          desc="All gates pass → GATE_SIGNAL_PASSED. Entry price = next M15 open."
          formula="entry = next_bar.open  ·  risk = SL − entry  ·  qty = 1.5% × equity / risk / contract_size"
        />
        <Arrow tone="bear" />

        <GateGroup
          title="Final safety gates"
          tone="bear"
          gates={[
            {
              label: "Risk sanity",
              ok: "0 < risk < 2% × entry",
              fail: "risk ≤ 0 or > 2% → reject",
            },
            {
              label: "Min risk floor",
              ok: "risk_units ≥ $0.50 (XAU broker-tradeable)",
              fail: "risk too tight — reject",
            },
            {
              label: "Dedup",
              ok: "(entry_ts, side, leg) not seen before",
              fail: "duplicate → reject",
            },
            {
              label: "Broker submit",
              ok: "DWX bridge accepts order → filled at market",
              fail: "spread > $0.50 or kill-switch → reject",
            },
          ]}
        />
        <Arrow tone="bear" />

        <Step
          n="6"
          title="Bracket walker — exit logic"
          tone="bear"
          desc="Each subsequent M15 bar walks brackets against high/low."
          detail={
            <ul className="list-disc pl-4 space-y-0.5">
              <li>TP hit (close ≤ TP) → close full at TP</li>
              <li>SL hit (close ≥ SL) → close full at SL</li>
              <li>+1R hit (partial TP) → close 50% at +1R, move SL to breakeven for rest</li>
              <li>24h elapsed (96 M15 bars) → TIMEOUT exit at bar close</li>
            </ul>
          }
        />
      </div>

      <aside className="col-span-12 lg:col-span-5 space-y-3">
        <div className="text-ds-md font-semibold text-transparent mb-3 select-none" aria-hidden>
          .
        </div>
        <div className="border border-bear/40 rounded-ds p-4 bg-bear/[0.05]">
          <div className="text-ds-md font-semibold text-bear mb-2">Locked config · D</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-ds-sm">
            <dt className="text-ink-muted">Direction</dt><dd className="text-ink-primary">SHORT</dd>
            <dt className="text-ink-muted">Base TF</dt><dd className="text-ink-primary">M15</dd>
            <dt className="text-ink-muted">Pivot lookback</dt><dd className="text-ink-primary">lb = 3</dd>
            <dt className="text-ink-muted">Session</dt><dd className="text-ink-primary">all (24/7)</dd>
            <dt className="text-ink-muted">Regime</dt><dd className="text-ink-primary">any</dd>
            <dt className="text-ink-muted">Max hold</dt><dd className="text-ink-primary">24h (96 bars)</dd>
            <dt className="text-ink-muted">SL buffer</dt><dd className="text-ink-primary">0.02 × Δ above HIGH</dd>
            <dt className="text-ink-muted">TP extension</dt><dd className="text-ink-primary">2.618 × Δ below LOW</dd>
            <dt className="text-ink-muted">Partial TP</dt><dd className="text-ink-primary">50% @ +1R → SL→BE</dd>
            <dt className="text-ink-muted">Min risk floor</dt><dd className="text-ink-primary">$0.50 / oz</dd>
            <dt className="text-ink-muted">Cost model</dt><dd className="text-ink-primary">$0.65 / trade</dd>
          </dl>
        </div>

        <PriceDiagram side="short" />
      </aside>
    </div>
  );
}

// ── LIVE LOOP FLOW ──

function LiveLoopFlow() {
  return (
    <div className="space-y-4">
      <div className="text-ds-md font-semibold text-info tracking-wide">
        LIVE LOOP · what happens every 15 minutes when a new M15 bar closes
      </div>

      <TickBanner />

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-8 space-y-0">
          <Step
            n="1"
            title="MT5 EA closes M15 bar and writes JSON"
            tone="info"
            desc="Every 15 min at :00 :15 :30 :45 UTC (broker server = UTC+3), MT5's DWX_Server EA appends the just-closed OHLC to Common/Files/DWX/bars_XAUUSD_ecn_M15.json."
            detail={
              <div className="space-y-1">
                <div>Files updated on each M15 close:</div>
                <ul className="list-disc pl-4 space-y-0.5">
                  <li><code className="text-info">bars_XAUUSD_ecn_M15.json</code> — last N M15 bars (rolling)</li>
                  <li><code className="text-info">bars_XAUUSD_ecn_D1.json</code> — daily bars (regime input)</li>
                  <li><code className="text-info">market_data.json</code> — live bid/ask/spread (per-tick, not per-bar)</li>
                  <li><code className="text-info">account_info.json</code> — balance / equity / margin (continuous)</li>
                  <li><code className="text-info">open_orders.json</code> — snapshot of open positions</li>
                </ul>
              </div>
            }
          />
          <Arrow />

          <Step
            n="2"
            title="LiveClock detects new bar (polling loop)"
            desc="Python live runner polls DWX every 1 second. It reads bars_XAUUSD_ecn_M15.json, compares latest timestamp to `provider._last_yielded_ts`. If new bar exists (> last yielded), it's yielded as a Bar object into the engine loop."
            formula="if latest_bar.ts > last_yielded_ts: yield Bar; last_yielded_ts = latest_bar.ts"
            detail={
              <>Server time (UTC+3) → UTC conversion via <code className="text-info">server_utc_offset_hours=3</code>. Only ONE bar is yielded per tick, not the whole history.</>
            }
          />
          <Arrow />

          <Step
            n="3"
            title="Engine reads history_up_to(bar.timestamp)"
            tone="info"
            desc="Provider returns a view (not a copy) of the full M15 dataframe up to and including the just-closed bar. Used by strategy for regime aggregation + swing tracker lookups. NO re-fetch from disk — memory cache."
            formula="history = provider._df[provider._df.timestamp <= bar.timestamp]  (searchsorted O(log n))"
            detail="Cost: ~1μs slice via numpy searchsorted. Zero disk I/O per tick after startup."
          />
          <Arrow />

          <Step
            n="4"
            title="Strategy state carries forward (no re-scan)"
            desc="on_bar receives (state, bar, history). state holds all trackers built up bar-by-bar. Nothing recomputed from scratch each tick."
            detail={
              <div className="space-y-1">
                <div>State fields alive across ticks:</div>
                <ul className="list-disc pl-4 space-y-0.5">
                  <li><code className="text-info">pivot_tracker</code> — sliding 7-bar window (lb=3 × 2 + center)</li>
                  <li><code className="text-info">regime_tracker</code> — D1 EMA fast/slow + ATR (recomputed only when new D1 bar closes)</li>
                  <li><code className="text-info">swing_tracker</code> — last 20 M15 bars (lb=3 window for signal-bar match)</li>
                  <li><code className="text-info">last_H, last_L, last_H_ts, last_L_ts</code> — most-recent confirmed pivots</li>
                  <li><code className="text-info">pending_setups</code> — dict[leg → list of FibSetup] awaiting signal-bar match</li>
                  <li><code className="text-info">pending_entries</code> — list[(leg, setup)] queued for next-bar entry</li>
                  <li><code className="text-info">consumed_setup_keys</code> — set of (leg, confirm_ts) already fired</li>
                  <li><code className="text-info">prev_open, prev_close</code> — prior bar's OHLC for confirm-candle check</li>
                </ul>
              </div>
            }
          />
          <Arrow />

          <Step
            n="5"
            title="on_bar runs the FULL decision chain"
            tone="info"
            desc="Deterministic pipeline (identical in BT and live). Each step emits gate events that persist to bt_signals."
            detail={
              <ol className="list-decimal pl-4 space-y-0.5">
                <li>Finalize any pending_entries queued at bar[k-1] → order emitted, added to consumed_setup_keys</li>
                <li>Update H1 pivots + regime from history</li>
                <li>Update D1 regime tracker</li>
                <li>Update M5 swing tracker (uses last 20 bars)</li>
                <li>Detect NEW confirmed pivot (lb=3 → confirms after 3 bars, so at k-3)</li>
                <li>Spawn new setups per leg (LONG/SHORT) if pivot ordering valid</li>
                <li>Walk pending_setups → match signal-bar OR invalidate/expire</li>
                <li>Cache prev_open/prev_close for next bar's confirm check</li>
              </ol>
            }
          />
          <Arrow />

          <Step
            n="6"
            title="Emit gate events (persist to bt_signals)"
            desc="Every gate site emits a StrategyEvent (GATE_*). Engine's on_strategy_event callback writes to bt_signals table."
            detail={
              <>16 gate types. Zero-miss = every decision (pass or fail) leaves an audit trail. Dashboard <code className="text-info">/signals</code> page decodes them.</>
            }
          />
          <Arrow />

          <Step
            n="7"
            title="On SIGNAL_PASSED: order goes to broker"
            tone="success"
            desc="Same-tick order submit (live) or next-bar-open (BT). LiveSafetyBroker wraps the raw DWX broker with 5 checks."
            detail={
              <ul className="list-disc pl-4 space-y-0.5">
                <li>demo check (server contains &quot;demo&quot;)</li>
                <li>kill-switch file check (LIVE_DISABLED)</li>
                <li>max_open_positions (broker total ≤ 4)</li>
                <li>max_spread ($0.50)</li>
                <li>Sizer replaces qty=1.0 placeholder → Model B (equity × 1.5% / stop / contract)</li>
                <li>max_lot cap (2.0)</li>
                <li>DWX writes OPEN|SYMBOL|BUY|QTY|... command file</li>
                <li>EA reads, submits, writes response with ticket + fill price</li>
                <li>Python receives fill → runs slip-ratio check (actual stop / expected ≤ 1.15)</li>
                <li>If slip too high → immediately CLOSE and drop trade</li>
              </ul>
            }
          />
          <Arrow />

          <Step
            n="8"
            title="Bracket walker on every open trade"
            desc="After the on_bar step, engine walks each open trade's OHLC against SL/TP/BE. Updates MFE/MAE. If partial_tp_at_r crossed → walker moves SL to entry AND triggers on_partial_tp callback → broker gets CLOSE_PARTIAL + MODIFY(SL=entry)."
            detail={
              <ul className="list-disc pl-4 space-y-0.5">
                <li>close ≥ TP → EXIT_TP</li>
                <li>close ≤ SL → EXIT_SL (or SL_BE if partial fired earlier)</li>
                <li>bars_held ≥ 48/96 → EXIT_TIMEOUT</li>
                <li>All exit events emit journal event + trigger reconciler</li>
              </ul>
            }
          />
          <Arrow />

          <Step
            n="9"
            title="On exit: reconcile with broker deal history"
            tone="info"
            desc="Live runner reads closed_orders.json for the broker's authoritative deal record. Aggregates multiple deals per position_id (partial + final). Writes broker_gross_usd / broker_commission_usd / broker_swap_usd / broker_net_usd + broker_exit_reason + broker_close_ts to bt_trades."
            detail="Walker net_r remains the strategy-space R metric. Broker columns are truth for real $ P&L. Dashboard trades page shows both side-by-side."
          />
          <Arrow />

          <Step
            n="10"
            title="Account snapshot + tick advance"
            desc="Read account_info.json → persist bt_account_snapshot with balance/equity/open_positions. Engine loop returns to LiveClock.tick() to wait for the next M15 close."
            formula="LiveClock polls every 1s. Blocks up to poll_interval_s until next bar timestamp exceeds last_yielded_ts."
          />
        </div>

        <aside className="col-span-12 lg:col-span-4 space-y-3">
          <div className="text-ds-md font-semibold text-transparent mb-3 select-none" aria-hidden>
            .
          </div>

          <PerTickIO />
          <StateFootprint />
          <BarWarmupNote />
        </aside>
      </div>

      <SharedLiveNotes />
    </div>
  );
}

function TickBanner() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
      <BannerStat label="Tick cadence" value="15 min" tone="info" />
      <BannerStat label="Bars pulled per tick" value="1 (newest closed)" tone="bull" />
      <BannerStat label="Disk reads per tick" value="~4 JSON files" tone="neutral" />
      <BannerStat label="State carry-fwd" value="8 trackers" tone="neutral" />
    </div>
  );
}

function BannerStat({ label, value, tone }: { label: string; value: string; tone: "info" | "bull" | "neutral" }) {
  const toneCls = tone === "info" ? "border-info/40 bg-info/[0.06]"
    : tone === "bull" ? "border-bull/40 bg-bull/[0.06]"
    : "border-line-base bg-bg-elevated";
  return (
    <div className={`border ${toneCls} rounded-ds p-3`}>
      <div className="text-ds-xs text-ink-muted uppercase tracking-wide">{label}</div>
      <div className="text-ds-md font-semibold text-ink-primary mt-1">{value}</div>
    </div>
  );
}

function PerTickIO() {
  return (
    <div className="border border-line-base rounded-ds p-4 bg-bg-surface">
      <div className="text-ds-sm font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Per-tick I/O
      </div>
      <div className="space-y-2 text-ds-xs">
        {[
          { file: "bars_M15.json", op: "read", detail: "detect new bar" },
          { file: "bars_D1.json", op: "read", detail: "regime aggregation" },
          { file: "market_data.json", op: "read", detail: "spread check on submit" },
          { file: "account_info.json", op: "read", detail: "balance/equity snapshot" },
          { file: "open_orders.json", op: "read", detail: "position sync + safety count" },
          { file: "commands/*.txt", op: "write", detail: "OPEN/MODIFY/CLOSE (only on trade action)" },
          { file: "responses/*.json", op: "read", detail: "broker ack + fill price" },
        ].map((row, i) => (
          <div key={i} className="grid grid-cols-1 md:grid-cols-12 gap-1 md:gap-2 items-baseline">
            <code className="md:col-span-5 text-info break-all">{row.file}</code>
            <span className={`md:col-span-2 text-ds-xs uppercase font-semibold ${
              row.op === "read" ? "text-bull" : "text-warn"
            }`}>{row.op}</span>
            <span className="md:col-span-5 text-ink-secondary">{row.detail}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 pt-2 border-t border-line-subtle text-ds-xs text-ink-muted">
        Zero re-fetch of historical bars per tick. Provider caches M15 frame in memory at startup, appends new bars as they arrive.
      </div>
    </div>
  );
}

function StateFootprint() {
  return (
    <div className="border border-line-base rounded-ds p-4 bg-bg-surface">
      <div className="text-ds-sm font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Strategy state footprint
      </div>
      <div className="space-y-1.5 text-ds-xs">
        {[
          ["pivot_tracker", "7 M15 bars (lb=3 sliding window)"],
          ["regime_tracker", "D1 EMA fast/slow + ATR (last N days)"],
          ["swing_tracker", "20 M15 bars"],
          ["last_H / last_L", "2 floats + 2 timestamps"],
          ["pending_setups", "≤ 5 FibSetup per leg typical"],
          ["pending_entries", "≤ 2 entries queued (rare)"],
          ["consumed_setup_keys", "grows monotonically (dedup)"],
          ["prev_open / prev_close", "2 floats (confirm candle)"],
        ].map(([k, v], i) => (
          <div key={i} className="grid grid-cols-1 md:grid-cols-12 gap-1 md:gap-2">
            <code className="md:col-span-5 text-info break-all">{k}</code>
            <span className="md:col-span-7 text-ink-secondary">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function BarWarmupNote() {
  return (
    <div className="border border-warn/40 rounded-ds p-4 bg-warn/[0.05]">
      <div className="text-ds-sm font-semibold text-warn mb-2 uppercase tracking-wide">
        Warmup (once, at startup)
      </div>
      <div className="text-ds-xs text-ink-secondary space-y-1">
        <div>Runner reads last <span className="font-mono text-warn">200 M15 bars</span> from bars_M15.json.</div>
        <div>Replays through <code className="text-info">strat.on_bar()</code>.</div>
        <div>Emitted events <span className="text-bear font-semibold">DISCARDED</span> (not persisted, no orders sent).</div>
        <div>Only <span className="text-bull font-semibold">state</span> carries forward — pivots seeded, regime warm, prev_bar cache filled.</div>
        <div className="mt-2 pt-2 border-t border-warn/30">Post-warmup: <code className="text-info">pending_entries</code> cleared. <code className="text-info">consumed_setup_keys</code> retained (historical keys can't collide with future live keys — L99 audit verified).</div>
      </div>
    </div>
  );
}

function SharedLiveNotes() {
  return (
    <section className="glass rounded-ds p-4 mt-4">
      <div className="text-ds-md font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Parity chain (research = BT engine = live engine)
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <ParityCard
          title="Research → BT parity"
          verified="6/6 legs (fib_v2_intraday_a + _d, cross-symbol XAU/EUR)"
          how="tests/parity/test_parity_fib_v2_intraday_*.py — asserts trade-by-trade match vs research parquet."
        />
        <ParityCard
          title="BT → Live engine parity"
          verified="3/3 tests, 300 XAU M15 bars"
          how="tests/integration/test_bt_live_event_parity.py — same strategy, mode='bt' vs mode='live' event streams byte-identical."
        />
        <ParityCard
          title="Live engine → Real broker parity"
          verified="Per-trade via reconciler"
          how="closed_orders.json → broker_gross/comm/swap → bt_trades.broker_net_usd. Walker net_r + broker net_$ shown side-by-side on trades page."
        />
      </div>
      <div className="mt-4 pt-3 border-t border-line-subtle text-ds-xs text-ink-muted">
        L99 hostile audit (2026-07-01): 13 execution / parity blind spots reviewed. 4 real bugs fixed (slip-reject, partial-TP retry/safe-close, reconciler multi-deal aggregation, concurrent A+D). See <code className="text-info">docs/audit/L99_HOSTILE_AUDIT_2026-07-01.md</code>.
      </div>
    </section>
  );
}

function ParityCard({ title, verified, how }: { title: string; verified: string; how: string }) {
  return (
    <div className="border border-bull/40 rounded-ds p-3 bg-bull/[0.04]">
      <div className="text-ds-sm font-semibold text-bull mb-2">{title}</div>
      <div className="text-ds-xs text-ink-primary mb-2">✓ {verified}</div>
      <div className="text-ds-xs text-ink-muted">{how}</div>
    </div>
  );
}

// ── Price ladder mini-diagram ──

function PriceDiagram({ side }: { side: "long" | "short" }) {
  // Positions rendered top-to-bottom
  const isLong = side === "long";
  const rows = isLong
    ? [
        { label: "TP  (H + 2.618·Δ)", color: "text-bull", weight: "font-semibold", bar: "bg-bull" },
        { label: "HIGH pivot", color: "text-info", weight: "font-medium", bar: "bg-info" },
        { label: "Zone hi  (H − 0.382·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "Zone lo  (H − 0.786·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "LOW pivot / fib_100", color: "text-warn", weight: "font-medium", bar: "bg-warn" },
        { label: "SL  (LOW − 0.02·Δ)", color: "text-bear", weight: "font-semibold", bar: "bg-bear" },
      ]
    : [
        { label: "SL  (HIGH + 0.02·Δ)", color: "text-bear", weight: "font-semibold", bar: "bg-bear" },
        { label: "HIGH pivot / fib_100", color: "text-warn", weight: "font-medium", bar: "bg-warn" },
        { label: "Zone hi  (L + 0.786·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "Zone lo  (L + 0.382·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "LOW pivot", color: "text-info", weight: "font-medium", bar: "bg-info" },
        { label: "TP  (LOW − 2.618·Δ)", color: "text-bull", weight: "font-semibold", bar: "bg-bull" },
      ];
  return (
    <div className="border border-line-base rounded-ds p-4 bg-bg-surface">
      <div className="text-ds-sm font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Price ladder
      </div>
      <div className="space-y-1">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2 text-ds-xs">
            <span className={`w-1 h-4 ${r.bar} rounded-full`} />
            <span className={`${r.color} ${r.weight} font-mono`}>{r.label}</span>
          </div>
        ))}
        <div className="mt-2 pt-2 border-t border-line-subtle text-ds-xs text-ink-muted">
          Zone shaded → strategy waits here for {isLong ? "bullish" : "bearish"} confirmation candle.
        </div>
      </div>
    </div>
  );
}

// ── Shared cross-strategy notes ──

function SharedRules() {
  return (
    <section className="glass rounded-ds p-4 mt-6">
      <div className="text-ds-md font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Shared rules (both legs)
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <RuleCard
          title="Causality — no look-ahead"
          points={[
            "Pivot confirmed 3 bars AFTER center — no peek at future.",
            "Regime uses D1 features from LAST closed day (shift(1)).",
            "Entry price = NEXT bar's open, not signal bar's close.",
            "MFE/MAE tracked bar-by-bar close, never intra-bar.",
          ]}
        />
        <RuleCard
          title="Sizing — Model B asymmetric monthly"
          points={[
            "risk_$ = 1.5% × current equity per trade.",
            "Skim profits at month-end back to start balance.",
            "Eat losses — trade smaller next month (no claw-back).",
            "Never wipes — 0 wipeouts in 21yr backtest.",
          ]}
        />
        <RuleCard
          title="Safety brakes"
          points={[
            "max_lot cap: 0.01 lot (paper-live default; production tune).",
            "max_open_positions: 4 concurrent (research validated).",
            "max_spread: reject if spread > $0.50 at submit time.",
            "kill-switch file: touch LIVE_DISABLED → halt all live entries.",
            "demo-only enforcement: refuses non-demo accounts by default.",
          ]}
        />
        <RuleCard
          title="Dedup + friction"
          points={[
            "One entry per (bar_ts, side, leg) — first signal wins.",
            "Multi-pivot stacking on same bar → drop later duplicates.",
            "Min risk floor $0.50/oz — reject broker-untradeable stops.",
            "Same-bar opposite direction allowed (A long + D short = hedge).",
          ]}
        />
        <RuleCard
          title="Expected numbers (research @ 1.5% Model B, $5k start)"
          points={[
            "Net $ lifetime: +$816,401 (21 yrs)",
            "Avg / year: +$38,876",
            "Best year: +$124,648 (2013)",
            "Worst year: +$4,186 (2007) — still positive",
            "Positive years: 21/21",
            "Positive months: 174/244 (71%)",
            "Wipeouts: 0",
          ]}
        />
        <RuleCard
          title="Audit gates applied"
          points={[
            "15-point audit POST-DEDUP: ALL PASS",
            "Cross-symbol survival: XAU + EUR only",
            "Delay stress +1/+5/+10 bars: edge stays or improves",
            "Cost stress: alive to $0.80/trade, dead at $1.00 — JM at $0.65 safe",
            "IS/OOS ratio 0.96–1.16 — no overfit",
          ]}
        />
      </div>
    </section>
  );
}

function RuleCard({ title, points }: { title: string; points: string[] }) {
  return (
    <div className="glass rounded-ds-sm p-3">
      <div className="text-ds-sm font-semibold text-ink-primary mb-2">{title}</div>
      <ul className="space-y-1">
        {points.map((p, i) => (
          <li key={i} className="flex items-start gap-2 text-ds-xs text-ink-secondary">
            <span className="text-brass mt-0.5">•</span>
            <span>{p}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
